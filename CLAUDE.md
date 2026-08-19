# CLAUDE.md

Convenience layer for Claude-style coding agents working in this repository.

> **This file is not a source of truth.** [`AGENTS.md`](AGENTS.md) and the active
> phase specification define the rules for every agent. This document only
> summarises them and adds tool-specific navigation. If anything here appears to
> contradict `AGENTS.md`, `AGENTS.md` wins and the contradiction is a bug worth
> fixing.

---

## Mission

GLOBIN is a locally hosted, autonomous research and trading system for Binance
Global, built over a fixed 320-phase programme. It runs on one Windows machine,
uses only free components and only officially documented interfaces.

**It does not trade yet.** Check [`ROADMAP.md`](ROADMAP.md) for the current
phase before assuming any capability exists.

Phase 016 closed the first band and cut `v0.1.0`, the foundation baseline. What
that certifies — and the one criterion it could not — is in
[`docs/release/FOUNDATION_ACCEPTANCE.md`](docs/release/FOUNDATION_ACCEPTANCE.md).

---

## Read these first

| Question | Document |
|---|---|
| What are the binding rules? | [`AGENTS.md`](AGENTS.md) |
| What phase are we in? | [`ROADMAP.md`](ROADMAP.md), [`MEMORY.md`](MEMORY.md) |
| What is durable project truth? | [`MEMORY.md`](MEMORY.md) |
| What must all code satisfy? | [`docs/engineering/ENGINEERING_CONTRACT.md`](docs/engineering/ENGINEERING_CONTRACT.md) |
| When am I finished? | [`docs/engineering/DEFINITION_OF_DONE.md`](docs/engineering/DEFINITION_OF_DONE.md) |
| Which document wins a conflict? | [`docs/engineering/SOURCE_OF_TRUTH.md`](docs/engineering/SOURCE_OF_TRUTH.md) |
| Where does this file go? | [`docs/engineering/REPOSITORY_LAYOUT.md`](docs/engineering/REPOSITORY_LAYOUT.md) |
| What must a host be capable of, and what does a compatibility fingerprint mean? | [`docs/engineering/ENVIRONMENT_CAPABILITY.md`](docs/engineering/ENVIRONMENT_CAPABILITY.md), [ADR-0075](docs/adr/0075-native-architecture-is-measured-through-one-adapter-and-a-fingerprint-excludes-what-moves.md) |
| How is a credential handed to GLOBIN, and what decides it may be used? | [`docs/security/CREDENTIAL_FLOW.md`](docs/security/CREDENTIAL_FLOW.md), [ADR-0077](docs/adr/0077-a-credential-is-collected-at-a-console-and-a-permission-is-declared-rather-than-verified.md) |
| Could this lock actually be installed on this machine, offline? | [`docs/engineering/DEPENDENCY_MATERIALIZATION.md`](docs/engineering/DEPENDENCY_MATERIALIZATION.md), [ADR-0078](docs/adr/0078-the-second-lock-reader-is-the-reference-implementation-and-a-cache-is-not-a-source-of-trust.md) |
| Where does a secret actually live, and what will never display one? | [`docs/security/SECRET_STORE.md`](docs/security/SECRET_STORE.md), [ADR-0074](docs/adr/0074-the-secret-store-is-the-windows-credential-manager-and-rotation-is-constructed.md) |
| Where does a key too large for the store live, and what does that not promise? | [`docs/security/SECRET_VAULT.md`](docs/security/SECRET_VAULT.md), [ADR-0083](docs/adr/0083-a-second-secret-mechanism-is-admitted-by-arithmetic-and-carries-its-own-integrity-check.md) |
| What may GLOBIN run without, and what does it refuse to start without? | [`docs/engineering/DEGRADED_OPERATION.md`](docs/engineering/DEGRADED_OPERATION.md), [`docs/engineering/degradation-contract.toml`](docs/engineering/degradation-contract.toml) |
| How does a running GLOBIN answer questions about itself over HTTP? | [`docs/engineering/DIAGNOSTICS_ENDPOINT.md`](docs/engineering/DIAGNOSTICS_ENDPOINT.md), [ADR-0072](docs/adr/0072-the-diagnostics-surface-is-loopback-only-read-only-and-bounded-by-construction.md) |
| How do I write documentation? | [`docs/engineering/DOCUMENTATION_STANDARD.md`](docs/engineering/DOCUMENTATION_STANDARD.md) |
| How is the system structured? | [`docs/architecture/README.md`](docs/architecture/README.md) |
| Which layer may import which? | [`docs/architecture/dependency-rules.toml`](docs/architecture/dependency-rules.toml) |
| Why is the architecture like this? | [`docs/ARCHITECTURE_PRINCIPLES.md`](docs/ARCHITECTURE_PRINCIPLES.md) |
| Why was X decided? | [`docs/adr/README.md`](docs/adr/README.md) |
| What sources may I trust? | [`docs/SOURCE_POLICY.md`](docs/SOURCE_POLICY.md) |
| May I add this dependency? | [`docs/DEPENDENCY_POLICY.md`](docs/DEPENDENCY_POLICY.md), [`docs/engineering/dependency-reviews.toml`](docs/engineering/dependency-reviews.toml) |
| Where may a secret live, and what is redacted? | [`docs/security/SECURITY_BASELINE.md`](docs/security/SECURITY_BASELINE.md) |
| How do I report or respond to a vulnerability? | [`SECURITY.md`](SECURITY.md), [`docs/security/VULNERABILITY_RESPONSE.md`](docs/security/VULNERABILITY_RESPONSE.md) |
| Who owns this path, and is a change to it security-sensitive? | [`docs/security/GOVERNANCE.md`](docs/security/GOVERNANCE.md), [`.github/CODEOWNERS`](.github/CODEOWNERS) |
| Which Windows, which Python, and how do I build `.venv`? | [`docs/engineering/RUNTIME_BASELINE.md`](docs/engineering/RUNTIME_BASELINE.md), [`docs/engineering/runtime-contract.toml`](docs/engineering/runtime-contract.toml) |
| Does the library I need have a wheel for that Python? | [`docs/engineering/WHEEL_AVAILABILITY.md`](docs/engineering/WHEEL_AVAILABILITY.md), [`docs/engineering/wheel-survey.toml`](docs/engineering/wheel-survey.toml) |
| Is this machine still the one the gates were measured on? | [`docs/engineering/ENVIRONMENT_DRIFT.md`](docs/engineering/ENVIRONMENT_DRIFT.md), [`docs/engineering/drift-policy.toml`](docs/engineering/drift-policy.toml) |
| What version of a dependency will actually be installed? | [`docs/engineering/DEPENDENCY_LOCKING.md`](docs/engineering/DEPENDENCY_LOCKING.md), [`docs/engineering/lock-policy.toml`](docs/engineering/lock-policy.toml) |
| Which checks must pass before a long-running process starts, and which answers decay? | [`docs/engineering/PREFLIGHT_SUITE.md`](docs/engineering/PREFLIGHT_SUITE.md), [ADR-0080](docs/adr/0080-a-check-declares-whether-its-answer-survives-the-run.md) |
| Which source set this value, and what changed since last run? | [`docs/engineering/CONFIGURATION_EVIDENCE.md`](docs/engineering/CONFIGURATION_EVIDENCE.md), [ADR-0081](docs/adr/0081-configuration-explains-itself-through-two-fingerprints-and-one-manifest.md) |
| How does a GLOBIN process decide it may start? | [`docs/engineering/BOOTSTRAP.md`](docs/engineering/BOOTSTRAP.md), [ADR-0056](docs/adr/0056-phase-021-widens-to-deliver-the-application-bootstrap.md) |
| Does the installed numerical stack actually compute correctly? | [`docs/engineering/SCIENTIFIC_STACK.md`](docs/engineering/SCIENTIFIC_STACK.md), [`docs/engineering/stack-contract.toml`](docs/engineering/stack-contract.toml) |
| Where does a running GLOBIN keep state, and how does it stop? | [`docs/engineering/RUNTIME_FILESYSTEM.md`](docs/engineering/RUNTIME_FILESYSTEM.md), [ADR-0059](docs/adr/0059-the-mutable-runtime-tree-is-user-local-and-one-coordinator-is-proved-by-a-lock.md) |
| What must a secret store satisfy, and what does Windows actually offer? | [`docs/security/SECRET_STORE_CONTRACT.md`](docs/security/SECRET_STORE_CONTRACT.md) |
| How do I test, and where does a test go? | [`docs/TESTING_STRATEGY.md`](docs/TESTING_STRATEGY.md) |
| Which error do I raise? | [`src/globin/errors.py`](src/globin/errors.py), [ADR-0022](docs/adr/0022-error-taxonomy-rooted-in-one-type.md) |
| How do I express a price or a quantity? | [`docs/VALUE_TYPES_POLICY.md`](docs/VALUE_TYPES_POLICY.md) |
| How do I write a value down and read it back? | [`docs/SERIALIZATION_POLICY.md`](docs/SERIALIZATION_POLICY.md) |
| Which checks must pass? | [`docs/engineering/QUALITY_GATES.md`](docs/engineering/QUALITY_GATES.md) |
| Why these lint and type rules? | [`docs/engineering/STATIC_ANALYSIS.md`](docs/engineering/STATIC_ANALYSIS.md) |
| How do I commit? | [`docs/GIT_WORKFLOW.md`](docs/GIT_WORKFLOW.md) |
| How is a version chosen, and a release cut? | [`docs/release/RELEASE_POLICY.md`](docs/release/RELEASE_POLICY.md) |
| What changed between versions? | [`CHANGELOG.md`](CHANGELOG.md) |
| Is the *environment* band complete, and on what evidence? | [`docs/release/ENVIRONMENT_ACCEPTANCE.md`](docs/release/ENVIRONMENT_ACCEPTANCE.md), [`docs/engineering/environment-acceptance.toml`](docs/engineering/environment-acceptance.toml) |
| Were Phases 017-032 drawn at the right granularity? | [`docs/engineering/GRANULARITY_REVIEW.md`](docs/engineering/GRANULARITY_REVIEW.md), [`docs/engineering/scope-amendments.toml`](docs/engineering/scope-amendments.toml) |
| How does an operator get from a clean clone to a host that starts? | [`docs/engineering/PROVISIONING.md`](docs/engineering/PROVISIONING.md), [ADR-0085](docs/adr/0085-a-plan-is-derived-from-a-report-and-one-module-may-start-a-process.md) |
| Is the foundation band complete, and on what evidence? | [`docs/release/FOUNDATION_ACCEPTANCE.md`](docs/release/FOUNDATION_ACCEPTANCE.md), [`docs/engineering/foundation-acceptance.toml`](docs/engineering/foundation-acceptance.toml) |
| What does Binance actually document, and how sure are we? | [`docs/engineering/BINANCE_API_REALITY.md`](docs/engineering/BINANCE_API_REALITY.md), [ADR-0087](docs/adr/0087-the-api-reality-registry-is-declared-with-provenance-and-drift-is-measured-in-two-regimes.md) |
| What does this term mean? | [`docs/GLOSSARY.md`](docs/GLOSSARY.md) |

---

## Repository navigation

```text
GLOBIN/
├── src/globin/          Python package, in five architectural layers.
│   ├── project_contract.py   Identity and policy invariants
│   ├── roadmap.py            The 20 immutable phase bands
│   ├── errors.py             The error taxonomy; above the layer stack
│   ├── domain/               Pure concepts, values and rules
│   ├── ports/                Abstract contracts, as typing.Protocol
│   ├── application/          Use cases, coordinating domain through ports
│   ├── adapters/             Concrete implementations; the only I/O
│   └── runtime/              Composition root
├── tests/               The suite; a test's directory decides its marker
│   ├── support.py       Importable helpers (conftest.py holds fixtures only)
│   ├── smoke/           Fastest signal that the tree is not broken
│   ├── contract/        Project rules asserted executably
│   ├── architecture/    The layer contract against the real import graph
│   ├── unit/            One unit, dependencies substituted
│   ├── property/        Invariants over generated input (Hypothesis)
│   └── integration/     Several components together, still local
├── config/              GLOBIN's own configuration; four profiles, none set yet
├── pylock.toml          The runtime dependencies, resolved and hash-pinned
├── pylock.dev.toml      The development toolchain, resolved and hash-pinned
│                        NOTE: a running GLOBIN's mutable state is NOT in this
│                        tree. It is user-local; see RUNTIME_FILESYSTEM.md.
├── tools/quality/       The canonical quality entrypoint; CI runs this too
│   ├── supply/          Dependency inventory, CycloneDX SBOM, audit, secrets
│   └── governance/      Code ownership, security policy, sensitive-path coverage
├── docs/
│   ├── architecture/    Layer contract, C4 system context and container views
│   ├── engineering/     How work is done: contracts and standards
│   ├── security/        Secret rules, vulnerability runbook, ownership model
│   ├── adr/             Architecture Decision Records + TEMPLATE.md
│   └── research/        Per-phase source ledgers
├── .github/             Templates, and the verification-only CI workflow
└── scripts/verify.ps1   The single verification gate
```

Dependencies point **inward only**: `runtime` → `adapters` → `application` →
`ports` → `domain`. The permitted directions are declared in
[`docs/architecture/dependency-rules.toml`](docs/architecture/dependency-rules.toml)
and enforced by `tests/architecture/test_architecture_contract.py`. Do not add a second copy
of that matrix anywhere.

There is deliberately no scaffolding for future components. Directories appear
when they hold real content. Full placement rules:
[`docs/engineering/REPOSITORY_LAYOUT.md`](docs/engineering/REPOSITORY_LAYOUT.md).

---

## Command discipline

The host is **Windows**. The primary shell is PowerShell; a Bash tool is also
available and takes POSIX syntax. Do not mix the two in one invocation.

**Build the project environment before anything else.** Since Phase 017 the gate
runs under `.venv\Scripts\python.exe` and refuses to run without it. Once, per
clone:

```bash
powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
```

Automation never activates the environment; it addresses the interpreter directly,
so `PATH` order cannot change what runs. Reasoning and troubleshooting:
[`docs/engineering/RUNTIME_BASELINE.md`](docs/engineering/RUNTIME_BASELINE.md).

The full gate, which is what you must run before committing:

```bash
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
```

It delegates to the canonical quality command, which is also what CI runs. Every
check is a name in `tools/quality/commands.py`; do not add a check anywhere else.

```bash
python -m tools.quality full
```

Individual checks, when iterating:

```bash
python -m tools.quality fast
```

```bash
python -m pytest -q
```

```bash
python -m tools.quality property
```

```bash
python -m tools.quality lint
```

```bash
python -m tools.quality typecheck
```

Only `fix` and `reformat` modify the tree. Every other command reports and
changes nothing.

One command answers a different question from the rest — not "is this tree good"
but "did this CI run establish that it is". It reads the results of a run's jobs
and the evidence they published, and reduces the two to one verdict. Run locally
it aggregates whatever `evidence` last wrote, using the same evaluator CI uses:

```bash
python -m tools.quality aggregate
```

One more sits outside `full`, and for a reason none of the others has: it
**reaches the network**. `pip-audit` resolves a requirements file against an
index and queries an advisory service, and the capability probe asks GitHub
about repository settings. `full` runs before every commit and must work on an
aeroplane, so this is separate:

```bash
python -m tools.quality supply
```

It reads the three registers that declare a dependency and reports where they
disagree, renders them as a deterministic CycloneDX 1.7 SBOM, audits the
declared toolchain, scans tracked content for credentials, and records what the
platform will and will not do. `--offline` skips both network calls and records
them as unmeasured — which is never a pass, so an offline run cannot exit `0`.
Adding a dependency is a written decision:
[`docs/DEPENDENCY_POLICY.md`](docs/DEPENDENCY_POLICY.md).

Its sibling asks the other half of the same question — not what this repository
depends on, but what it is answerable for — and unlike `supply` it **reaches
nothing**:

```bash
python -m tools.quality governance
```

It compares [`docs/engineering/governance.toml`](docs/engineering/governance.toml)
against the tree in both directions: every governing file present, exactly one
CODEOWNERS file, every security-sensitive path specifically owned, every owned
pattern matching something real, the security policy still carrying the section
that names its reporting channel, and no public issue template collecting
vulnerability detail. The assertions that gate a commit are in
`tests/contract/test_governance_contract.py`, which the ordinary suite runs; the
command exists to write the manifest. Reasoning:
[`docs/security/GOVERNANCE.md`](docs/security/GOVERNANCE.md).

Its job in CI is the check named `Quality gate`, which is the one to mark as
required on `master`. Branch protection is a repository setting and no file here
can change it — see
[`docs/engineering/QUALITY_GATES.md`](docs/engineering/QUALITY_GATES.md).

A third sibling asks whether the foundation may be **frozen** — and, like
`governance`, reaches nothing:

```bash
python -m tools.quality release
```

It reads [`docs/engineering/foundation-acceptance.toml`](docs/engineering/foundation-acceptance.toml)
and checks the release contract against the tree: no criterion identifier
repeated or misfiled, every criterion naming evidence that exists, every blocking
criterion passing, the version a taggable final release, the changelog announcing
it exactly once, and the release documents and notes configuration present and
well formed. It writes the manifest, the machine-readable acceptance record and
`SHA256SUMS` into `.globin/release/`.

A second subcommand adds the questions that are about the working tree rather
than the commit — branch, cleanliness, agreement with the remote. Note the **dot**
rather than a space: the command table takes one word, so a subcommand is passed
to the sub-package directly, and `python -m tools.quality release ready` is a
usage error rather than a run.

```bash
python -m tools.quality.release ready
```

Run `ready` immediately before cutting a release, not on every push: two runs of
it can legitimately disagree, which is why CI runs `check`. Procedure and
reasoning: [`docs/release/RELEASE_POLICY.md`](docs/release/RELEASE_POLICY.md) and
[ADR-0049](docs/adr/0049-a-version-has-one-source-and-a-release-is-frozen-evidence.md).

A fourth sibling asks which machine the other gates were measured on, and like
`governance` and `release` it **reaches nothing**:

```bash
python -m tools.quality runtime
```

It reads [`docs/engineering/runtime-contract.toml`](docs/engineering/runtime-contract.toml)
and compares this host against it: the operating system and its kernel version,
the interpreter's implementation, minor line, patch floor, architecture, width and
build, the project environment's provenance and settings, and where `pip` would
install from. It writes `.globin/runtime/runtime-manifest.json`, in which every
path outside the repository is a fingerprint rather than a path.

Run it through the environment's own interpreter or it measures the wrong one —
`scripts/preflight.ps1` does that for you. Its `bootstrap` subcommand is the only
thing here that creates anything, and it writes only inside the repository:

```bash
python -m tools.quality.runtime bootstrap --recreate
```

Nothing in it edits the registry, the PATH, the execution policy, or any
interpreter outside `.venv`. Reasoning:
[`docs/engineering/RUNTIME_BASELINE.md`](docs/engineering/RUNTIME_BASELINE.md) and
[ADR-0050](docs/adr/0050-the-runtime-is-a-declared-contract-and-venv-is-its-only-environment.md).

A fifth sibling asks whether the libraries this programme schedules can actually
run on that interpreter, and like the three above it **reaches nothing**:

```bash
python -m tools.quality wheels
```

It reads [`docs/engineering/wheel-survey.toml`](docs/engineering/wheel-survey.toml)
and recomputes every recorded verdict from the wheel filenames recorded beside it,
comparing its target against the runtime contract as it goes. The filenames are in
the file precisely so the verdict can be checked rather than believed: an entry
claiming a wheel exists whose own evidence does not support it fails without
asking anything. It writes `.globin/wheels/wheel-manifest.json`.

Its `probe` subcommand is the half that **does** reach PyPI, asking whether the
record is still true — a new release, a withdrawn wheel, a `Requires-Python` cap
tightened to exclude the pinned line:

```bash
python -m tools.quality.wheels probe
```

A gap is recorded and owned, never assumed: a verdict other than `available` must
name the phase answering for it, and only an unowned gap fails. Nothing here is
installed, resolved, locked or adopted — that is Phases 020-021. Reasoning:
[`docs/engineering/WHEEL_AVAILABILITY.md`](docs/engineering/WHEEL_AVAILABILITY.md)
and [ADR-0052](docs/adr/0052-wheel-availability-is-a-recorded-survey-whose-verdict-is-recomputed.md).

A sixth sibling asks the question none of the others can, because it needs two
measurements rather than one — not "is this machine acceptable" but "is this
machine what it was". Like the three above it, it **reaches nothing**:

```bash
python -m tools.quality drift
```

It compares this host against a baseline you accepted, classifies every
difference against
[`docs/engineering/drift-policy.toml`](docs/engineering/drift-policy.toml), and
recomputes each recorded repair verdict from the action declared beside it. It
writes `.globin/drift/drift-manifest.json`.

**It never records a baseline**, and with no baseline the verdict is `unmeasured`
rather than clean — a fresh clone exits `3`. Record one deliberately, on a host
you are willing to be held to:

```bash
python -m tools.quality.drift accept
```

It fails where `runtime` correctly passes, which is the reason it exists
separately: the contract declares a patch *floor*, so an interpreter that went
backwards satisfies it, and a `PIP_INDEX_URL` or a machine-wide `pip.ini`
appearing violates nothing at all.

Its third subcommand is the only thing here that writes outside its own evidence,
and it writes **only inside `.venv`**:

```bash
python -m tools.quality.drift repair
```

Exactly one fault is repairable in place. `pyvenv.cfg` is read at interpreter
start-up, so an environment that has gained access to the machine's global
packages is corrected by rewriting one key rather than by being destroyed —
which is what `RUNTIME_BASELINE.md` had advised, alongside four faults that do
need it. Everything else names what *you* should run, or names something outside
the repository that ADR-0050 forbids this tooling from touching. Reasoning:
[`docs/engineering/ENVIRONMENT_DRIFT.md`](docs/engineering/ENVIRONMENT_DRIFT.md)
and [ADR-0053](docs/adr/0053-drift-is-measured-against-an-accepted-baseline-and-repair-is-a-classification.md).

A seventh sibling asks what will actually be installed, and like the four above
it **reaches nothing**:

```bash
python -m tools.quality lock
```

It reads `pylock.dev.toml` and
[`docs/engineering/lock-policy.toml`](docs/engineering/lock-policy.toml), and
recomputes every claim the lock makes from the evidence inside it: that each of the
forty-nine packages carries a digest in a permitted algorithm, that every artefact
is served over HTTPS from the declared host, that a recorded wheel's PEP 425 tags
serve the pinned interpreter, and that the lock and the three declaration registers
agree about one version each. It writes `.globin/lock/lock-manifest.json`.

**It does not trust `pip`.** pip wrote the lock, and pip labels both `lock` and
`install -r pylock.toml` experimental; validating one with the other would
establish only that pip agrees with itself.

Its `installed` subcommand adds this environment, and is the one claim an offline
gate cannot make. It reports `unmeasured` unless run through the environment's own
interpreter:

```bash
.venv\Scripts\python.exe -m tools.quality.lock installed
```

Its other two subcommands **reach PyPI**, which is why they are subcommands. A
relock holds every workflow pin and the producer, so it records the transitive set
rather than upgrading the tools somebody chose; moving one is a separate, named act:

```bash
python -m tools.quality.lock relock
```

```bash
python -m tools.quality.lock upgrade ruff
```

A regenerated lock is checked before it is kept: one that is wrong *about itself*
is left in `.globin/lock/` with the committed file untouched, while one that merely
disagrees with the pins is kept and the exact edits are printed. `bootstrap`
installs from the lock and refuses rather than falling back; `-FromPins` is the
documented hand-crank. Reasoning:
[`docs/engineering/DEPENDENCY_LOCKING.md`](docs/engineering/DEPENDENCY_LOCKING.md)
and [ADR-0054](docs/adr/0054-the-toolchain-is-locked-with-pep-751-and-the-verdict-is-recomputed.md).

An eighth sibling asks whether the libraries this programme *adopted* actually
compute what GLOBIN assumes, and like the five above it **reaches nothing**:

```bash
.venv\Scripts\python.exe -m tools.quality stack
```

It reads [`docs/engineering/stack-contract.toml`](docs/engineering/stack-contract.toml)
and recomputes it against this environment: the declared target against the
runtime contract, every declared version against `pyproject.toml`, `pylock.toml`
and what is installed, each artefact's own record of the wheel it was built from,
and seven behaviour probes run against the real libraries. It writes
`.globin/stack/stack-manifest.json`.

**Run it through `.venv`** — `numpy` and `pandas` arrive with the runtime lock,
and through a bare interpreter the gate correctly reports two libraries that are
not installed, which is a true answer to the wrong question. It has no networked
subcommand at all, because what it asks is entirely answerable from this machine.

**Verifying is not adopting.** Nothing under `src/globin` imports either library
and `tests/architecture/test_stack_discipline.py` fails if anything starts; the
phase that has a legitimate use edits the stack contract in its own diff.
Reasoning: [`docs/engineering/SCIENTIFIC_STACK.md`](docs/engineering/SCIENTIFIC_STACK.md)
and [ADR-0058](docs/adr/0058-the-scientific-stack-is-verified-by-measurement-and-stays-in-the-approximate-regime.md).

A tenth sibling asks the question the ninth deliberately refused — not "is there
a device" but "does using it pay" — and like the seven above it **reaches
nothing**:

```bash
python -m tools.quality benchmark
```

It reads [`docs/engineering/benchmark-contract.toml`](docs/engineering/benchmark-contract.toml),
measures every workload it can with the declared warmup, repeat count and
reduction, and recomputes each verdict from the recorded nanoseconds against the
declared speedup threshold. It writes `.globin/benchmark/benchmark-manifest.json`.

**This is the one manifest that is not byte-stable between runs, and it says so.**
`run.observed` holds timings, which move; `findings` holds verdicts, which are a
function of the contract and those timings, and the determinism check covers the
findings half only. **Every CUDA workload records `unavailable` today**, naming
`torch` and Phase 183 — a measurement rather than a hole, because nothing here is
stubbed. Two traps are handled rather than remembered: a CUDA timing that does not
`synchronize()` measures submission and reports a speedup of hundreds, and a
threshold of `1.0` would recommend moves that lose once the transfer is paid for.
Reasoning: [`docs/engineering/GPU_BENEFIT.md`](docs/engineering/GPU_BENEFIT.md)
and [ADR-0062](docs/adr/0062-workload-benefit-is-measured-and-a-timing-is-not-evidence-of-reproducibility.md).

Phase 024 also gave the running process a way to say **how it is doing**, which is
a different question from whether it may start:

```bash
.venv\Scripts\globin.exe diagnostics snapshot --json
```

```bash
.venv\Scripts\globin.exe diagnostics bundle
```

`snapshot` reports `healthy`, `degraded` or `unhealthy` through the three exit
codes every gate already speaks, plus `22` when no snapshot could be produced at
all — a failure to measure a state rather than a state. **A measurement that was
not taken is never zero**: every numeric field carries an `Availability`, and no
instantaneous `cpu_percent` is reported because the first call on a process is
documented as meaningless. An unmeasurability the registry *predicted* does not
make a host amber, which is what stops CI — where `psutil` is absent on every run
— from reporting `degraded` forever. `bundle` writes a redacted archive, validates
it by **reopening the finished file** and comparing every digest, and publishes it
atomically into `cache/support/`; the allowlist is a table with no directory walk
anywhere. `memory` is a separate verb rather than a flag, because the allocator
tracer costs the whole process while it runs. Details:
[`docs/engineering/RUNTIME_HEALTH.md`](docs/engineering/RUNTIME_HEALTH.md) and
[`docs/engineering/SUPPORT_BUNDLE.md`](docs/engineering/SUPPORT_BUNDLE.md).

Phase 025 gave that process a **watchdog**, and Phase 026 gave it **telemetry**.

```bash
.venv\Scripts\globin.exe diagnostics watchdog
```

```bash
.venv\Scripts\globin.exe diagnostics telemetry --json
```

The watchdog's heartbeat is a **sequence, not a timestamp**, because a component
looping inside a wedged call rewrites a timestamp for ever; its escalation deadline
runs **from the stall, not from the request**, so a slow capture cannot postpone
death. Exit code 23.

Telemetry's central rule is that **cardinality is arithmetic rather than a hope**:
every attribute key declares a bounded value set, so the most series a metric family
can produce is a product computable when the descriptor is written, and a descriptor
that could exceed its own budget **cannot be constructed**. Every value is an integer
-- durations in nanoseconds, ratios in parts per million -- with a `2**53` ceiling
that is **not Python's limit** but every other JSON reader's. **Export is off by
default and "off" is an object graph rather than a flag**: no exporter, queue, pump
or thread exists, so opening no socket is structural. Phase 026's scrape listener is **gone** -- it served a registry GLOBIN never populated
and had no caller; Phase 027's endpoint replaced it. Details:
[`docs/engineering/RUNTIME_TELEMETRY.md`](docs/engineering/RUNTIME_TELEMETRY.md),
[`docs/TELEMETRY_POLICY.md`](docs/TELEMETRY_POLICY.md) and
[`docs/engineering/CONFIGURATION_LAYOUT.md`](docs/engineering/CONFIGURATION_LAYOUT.md).

Phase 027 gave that process a **loopback diagnostics surface**, and gave configuration
a **precedence**.

```bash
.venv\Scripts\globin.exe diagnostics endpoint --json
```

```bash
.venv\Scripts\globin.exe doctor --profile paper
```

Configuration now resolves from four documents and then the environment, in a declared
order: `precedence()` for the documents, `profile_from()` for the profile
(`--profile` beats `GLOBIN_PROFILE` beats the default), and `build_config_sources()` for
the chain. **An unrecognised `GLOBIN_` variable is refused**, and a credential-shaped one
is refused before it is read -- the prefix is what makes a typo detectable. A missing
document is an empty layer; a document that exists and cannot be read is not.
**`bootstrap check` now validates what a run will use** rather than the declared
defaults, so exit `14` arrives at the gate instead of at start-up.

The HTTP surface is **off by default**, and off means no server, socket, queue or worker
thread exists. Five read-only routes -- `/health/live`, `/health/ready`,
`/health/runtime`, `/metrics`, `/diagnostics/snapshot` (off again even when the surface
is on). **The bind address is a value type, not a literal and not a free string**:
`LoopbackAddress` refuses anything `ipaddress` does not call loopback, so
`diagnostics_http.bind_host` cannot *hold* a wildcard, a LAN address or a hostname.
`GET` and `HEAD` only, and `send_error` is overridden because defining two handlers
leaves the standard library answering every other verb with a **generic HTML page**.
Negotiation is **total with no 406** -- the scrape protocol's own answer when nothing
offered is supported is to serve Prometheus text 0.0.4. Exactly **one module** may reach
a socket, and `tests/architecture/test_library_discipline.py` fails if a second one does
or if that one spells any address at all. Details:
[`docs/engineering/DIAGNOSTICS_ENDPOINT.md`](docs/engineering/DIAGNOSTICS_ENDPOINT.md).

Phase 028 gave that process **somewhere to keep a credential**, and gave the host a
**capability inventory**.

```bash
.venv\Scripts\globin.exe diagnostics environment --json
```

The store is the **Windows Credential Manager** through `ctypes`, costing no new
dependency. A **reference is not a value**: the first is ordinary data, the second
has no string form, no `__dict__`, no encoder and no hash. One key builder folds
case, because the platform's target names collide **silently** -- a credential
written under one spelling is returned for another with no error at all. Rotation
moves the previous value aside **before** writing the new one, because a Windows
write *replaces* and there would otherwise be nothing left to retire. **GLOBIN still
holds no credentials**; it now has somewhere to put one, which is different.

Two measured facts the documentation does not carry: the oversize failure is an
**undocumented** `RPC_X_BAD_STUB_DATA`, and an **RSA-4096 key in PEM form does not
fit** the 2560-byte ceiling. Ed25519 is 122 bytes.

The inventory separates **native** from **process** architecture, and only
`IsWow64Process2` may answer the first -- Microsoft documents `GetNativeSystemInfo`
as reporting an ARM64 host *as if it were x86*, so where the modern API is absent
the answer is `UNKNOWN` rather than a guess. **An unmeasurable required capability
degrades rather than blocks**, which is what keeps CI's runner from going red for
ever. Exit code **24**, and it is deliberately not `10`: that means the host failed
the declared contract, this means it satisfies it and lacks a capability.

**Six libraries are now absent-safe** -- `psutil`, `opentelemetry`, `prometheus_client`,
`advapi32`, `kernel32` and, since Phase 031, `crypt32` -- each reached through one
factory in one adapter, each with an architecture tripwire, because the CI `quality`
job installs none of them. Do not add a second import site for any of them; add a
factory. Phase 031 also made *which arm each one took* something GLOBIN records
rather than discards, and `tests/architecture/test_degradation_discipline.py` fails
if a seventh factory appears without a row in the contract.

**Do not widen the bind address for remote access.** The type will not let you, and the
supported shape is a separate authenticated, TLS-capable collector that scrapes
`127.0.0.1` locally -- Phases 280 and 315.

`psutil` is the third runtime dependency and the **first this repository imports**.
It is reached through one factory in `globin/adapters/health.py` and nowhere else,
which `tests/architecture/test_probe_discipline.py` enforces.

Phase 029 gave GLOBIN a way to be **handed** a credential, and a way to **refuse
to use one**.

```bash
.venv\Scripts\globin.exe secrets set --environment paper --kind api_key --name venue_key
```

```bash
.venv\Scripts\globin.exe secrets list --json
```

Six verbs and no seventh -- `set`, `verify`, `list`, `delete`, `rotate`, `health` --
matching `SECRET_STORE_CONTRACT.md` section 5 exactly, with a contract test comparing
the two. Collection is **interactive only**: a pipe is refused *before* `getpass` is
called, because accepting one puts the key in shell history. A terminal that cannot
suppress echo aborts *before the operator types anything* -- the fallback warns before
it reads -- so **the value never exists** rather than existing and being discarded.
Whitespace is **refused, not stripped**. A real PEM key cannot be collected here at
all: it is multi-line, so it trips the control-character rule whatever its size.

Permission verification is containment against a declaration, and `VerificationState`
has **no member meaning confirmed** -- GLOBIN reaches no venue, so the rule that a
capability is a recorded state rather than a pass is enforced by there being nothing
to write. A demanded `transfer` is `WITHHELD` **whatever the declaration says**, and it
is checked *before* the declaration is consulted. `require_permitted` returns **without
touching the store** on a refusal. Exit code **25**, and deliberately not `15`: one
means store a credential, the other means change a key's permissions at the venue.

**`required` is still empty, and now empty by derivation** -- the registry exists and
Phase 038 fills it. Details:
[`docs/security/CREDENTIAL_FLOW.md`](docs/security/CREDENTIAL_FLOW.md).

Phase 030 turned the eighteen-check registry into a **suite**, and made configuration
**explain itself**.

```bash
.venv\Scripts\globin.exe bootstrap preflight
```

```bash
.venv\Scripts\globin.exe config explain logging.min_severity
```

Every check now declares whether its answer **survives the run**; eleven of the eighteen
do. `config.valid` is stable **because the snapshot is immutable**, not because documents
are -- an operator may edit `config/` mid-run and the process is not reading it again.
`state.previous_run` is stable because re-taking it later would read *this* run's record.
`RecheckPolicy` is validated at construction and **nothing executes it**: no process runs
long enough, so a scheduler would be a mechanism with no caller. `bootstrap preflight`
runs everything *and* gates -- the third combination of two switches that already existed
-- and adds **no exit code**. 26 stays free.

The precedence chain gained a source at **each end**, and the whole order follows one
rule -- narrowness. `--config PATH` sits above the four computed documents and **its
absence is fatal** where theirs is not; `--set KEY=VALUE` sits above the environment and
is validated against `known_keys()`, so there is no arbitrary path to accept. **Only keys
an operator typed enter that layer**, or the strongest source would set everything on
every run.

**Two fingerprints, and the split is the deliverable.** The semantic one excludes origins
-- moving a file is not a change -- and the evidence one includes them, so a value that
began arriving from the environment instead of a committed document *is*. **Comparison
reads digests, never displays**: two redacted displays are always equal, so a drift report
built on them would say "unchanged" about exactly the fields it could not see. **No
baseline is `unmeasured`, not clean.**

Two defects were found rather than built, and both are worth knowing. A
`ConfigurationError` clause written around the whole of `_bootstrap` silently turned a
Phase 021 exit code from `17` into `14` -- the existing suite caught it. And
`tomllib.TOMLDecodeError` is a **`ValueError`**, so neither `main` nor the pipeline caught
it; the path was unreachable until `--config` made it reachable. Details:
[`docs/engineering/PREFLIGHT_SUITE.md`](docs/engineering/PREFLIGHT_SUITE.md) and
[`docs/engineering/CONFIGURATION_EVIDENCE.md`](docs/engineering/CONFIGURATION_EVIDENCE.md).

Phase 029 also gave the *running* application eyes for its own dependencies, and added
a gate for whether they could be installed at all:

```bash
python -m tools.quality materialize
```

Until now a running GLOBIN walked every distribution's metadata and **threw the version
away**, so an environment two releases from its lock reported ready. It now carries an
inventory, a fingerprint that cannot see the lock's producer, and the caller that finally
sets `DEPENDENCY_UNREADY` -- a readiness word declared at Phase 027 that **nothing had
ever set**.

`packaging` is the ninth runtime dependency, adopted deliberately against ADR-0052's
earlier refusal and costing **nothing**: it was already in `pylock.toml` as a transitive.
It brought `packaging.pylock`, a complete PEP 751 implementation, so the runtime writes
**no second parser** -- and the two-reader tripwire now checks the delivered Phase 020
parser *against the reference implementation*.

The materialization gate **reaches no network because `plan.py` imports nothing that
could**, which is a property rather than a promise. An empty wheelhouse is `unmeasured`
and exits `3`, exactly as `drift` treats an unrecorded baseline -- artefacts are hundreds
of megabytes and are not committed, so a fresh clone has established nothing rather than
an absence. A corrupt cached artefact is **left in place and reported**: deleting it
destroys the diagnosis, and re-fetching would make the cache a network client.

**The clean room never touches your `.venv`**, held by three independent mechanisms, and
a decoy is proved byte-for-byte unchanged after both a successful and a failing run.
Details: [`docs/engineering/DEPENDENCY_MATERIALIZATION.md`](docs/engineering/DEPENDENCY_MATERIALIZATION.md).

A ninth sibling asks what this *machine* has rather than what the tree declares,
and like the six above it **reaches nothing**:

```bash
python -m tools.quality gpu
```

It reads [`docs/engineering/gpu-contract.toml`](docs/engineering/gpu-contract.toml)
and asks `nvidia-smi` only the fields that contract permits, recording a **state**
for each of five capabilities — device presence, driver version, compute
capability, CUDA runtime, CUDA toolkit. It writes `.globin/gpu/gpu-manifest.json`.

**Absence is a state, not a failure.** A host with no NVIDIA device records
`ABSENT` and exits `0`, which is what lets this run on CI's GPU-less runner;
`ERROR` always fails, because not knowing why differs from knowing why. The
contract declares an *interface*, never a baseline — no driver version is
committed, so nothing goes red on a driver update. Three field names are named as
**forbidden**: `nvidia-smi` refuses `cuda_version` outright *and asking breaks the
whole query*, and it answers two of its own `--version` labels with the word
*Deprecated*. All four traps were measured on this host, not remembered
([`docs/research/phase_023_sources.md`](docs/research/phase_023_sources.md)).
Detection is Phase 023; **which workloads benefit is Phase 024**, and nothing here
times anything. Reasoning:
[`docs/engineering/GPU_CAPABILITY.md`](docs/engineering/GPU_CAPABILITY.md) and
[ADR-0060](docs/adr/0060-gpu-capability-is-detected-and-the-runtime-explains-itself.md).

Since Phase 021 there is also an **application** command, which is not a gate and
does not live in that table. It exists once GLOBIN is installed, which
`scripts/bootstrap.ps1` now does:

```bash
.venv\Scripts\globin.exe doctor
```

```bash
.venv\Scripts\python.exe -m globin bootstrap check
```

Both reach one `main`; `doctor` reports and keeps going, `bootstrap check` refuses
at the first problem, and `bootstrap evidence` writes
`.globin/bootstrap/bootstrap-manifest.json`. Under `--json` standard output
carries JSON and nothing else. **It reaches no network**, and the exit code names
the failure class — `12` is the wrong environment, `13` a missing dependency, `14`
an invalid configuration, and since Phase 022 `20` means another GLOBIN
coordinator is already running. The full table, the remediation for each, and what
is deliberately *not* checked yet are in
[`docs/engineering/BOOTSTRAP.md`](docs/engineering/BOOTSTRAP.md).

Phase 022 gave that process somewhere to keep state. A running GLOBIN writes to a
**user-local** tree under `%LOCALAPPDATA%\GLOBIN\` — `state`, `cache`, `run`,
`tmp`, and since Phase 023 `logs` — which is deliberately *not* `.globin/`: that tree is evidence about this
repository, read by CI, and this one is state about this machine. **No secret, no
credential and no bulk data goes in either.** Every small document is published
atomically, and one coordinator per machine is guaranteed by an operating-system
lock whose *acquisition* decides ownership — **the lock file's existence proves
only that GLOBIN once ran**, so a stale one never blocks a start-up and is never
deleted on a guess. `doctor` probes that lock and does not keep it. What is
guaranteed on each kind of ending, and what is not, is in
[`docs/engineering/RUNTIME_FILESYSTEM.md`](docs/engineering/RUNTIME_FILESYSTEM.md).

Phase 023 gave that process a voice. `logs/` is the **only area appended to**, so
it is bounded by a validated rotation policy rather than trusted — a policy that
could not be honoured cannot be constructed. The three fault hooks
(`sys.excepthook`, `threading.excepthook`, `sys.unraisablehook`) are installed by
the composition root through an **injected registry** and put back on the way out;
`faulthandler` writes plain text to its own file, because a native traceback is
written by C and that is exactly why it still works when the interpreter cannot.
A bridge routes a dependency's standard-library records and Python's warnings into
GLOBIN's sinks — **GLOBIN's own call sites still do not use `logging`**, and
`tests/architecture/test_logging_discipline.py` fails if that changes. Redaction is
by field *name*, so a credential inside an exception message **is** written, and
that limit is stated rather than implied. Details:
[`docs/engineering/RUNTIME_DIAGNOSTICS.md`](docs/engineering/RUNTIME_DIAGNOSTICS.md).

One gate sits outside `full`, because it takes minutes rather than seconds:

```bash
python -m tools.quality mutation
```

It rewrites one module at a time inside a temporary copy of the tree and checks
whether the tests notice, then compares the survivors against
[`docs/engineering/mutation-baseline.toml`](docs/engineering/mutation-baseline.toml).
Nothing writes that file. Read a survivor's recorded argument before changing it
([ADR-0033](docs/adr/0033-mutation-testing-is-a-repository-native-ast-harness.md)).

Tests run against the source tree with no install step, because
`pythonpath = ["src"]` is set in `pyproject.toml`. There is no build in Phase 1.

Phase 031 gave GLOBIN a way to say **what it is running without**, and somewhere to
put a key that does not fit.

```bash
.venv\Scripts\globin.exe secrets doctor
```

Six absent-safe factories each choose between a working implementation and a
recording stand-in, and **which arm they took was thrown away** -- it survived
nowhere but an untyped dictionary inside one command, covering two of the six. A
declared registry now carries a **necessity** per component and a posture is folded
from what each factory actually returned. Three tiers: `required` refuses a start,
`optional` starts and names what stopped working, `opportunistic` changes nothing --
that third one being Phase 030's inherited rule, because a capability the registry
*predicted* absent must not make a host amber. **`advapi32` is declared required and
observed not-applicable** while nothing needs a credential, so the tier is real today
without refusing a start for a capability no caller uses. **The network is declared,
not probed**: a probe would be a mechanism with no caller *and* would remove a
guarantee the architecture tests currently prove. No new exit code -- 24 is reused
and **26 stays free**.

Alongside it, as the **fifteenth scope amendment**, a DPAPI vault -- and it scores
**one of ADR-0021's four conditions**, which ADR-0082 says plainly rather than argues
around. The store takes what fits its 2560-byte ceiling and the vault takes what does
not, reading **the same constant**, so the two are disjoint by arithmetic and there is
**no fallback edge** between them. `belongs_in_vault` takes no key type: a private key
that fits belongs in the store.

**The envelope carries its own integrity check, verified before the platform is
reached** -- Microsoft documents that `CryptUnprotectData` may succeed *with corrupted
output* and says not to rely on a code to detect tampering. The digest is **not** a
secret fingerprint: DPAPI derives a fresh key per call, so two protections of one
value differ. `CRYPTPROTECT_LOCAL_MACHINE` is defined **precisely so its absence can be
asserted**; the prompt structure is null and no such type exists in the package.
`LocalFree` crosses the module boundary as **one function, never a library handle**.

**The vault is a sibling directory, not a sixth `RuntimeArea`** -- all five areas
answer *yes* to "may this be deleted" and a vault answers *never*. It is created by
the first write, so its existence is itself evidence something was stored. **It does
not travel** between accounts or machines, and there is no backup: recovery is
re-enrolment. Details:
[`docs/engineering/DEGRADED_OPERATION.md`](docs/engineering/DEGRADED_OPERATION.md) and
[`docs/security/SECRET_VAULT.md`](docs/security/SECRET_VAULT.md).


Phase 032 closed the environment band, and gave the surface a **plan**.

```bash
.venv\Scripts\globin.exe bootstrap plan
```

```bash
.venv\Scripts\globin.exe bootstrap setup
```

**`setup` is not the cold-start path**, and `PROVISIONING.md` says so first: it is
installed *into* the environment it would create, so `scripts/bootstrap.ps1` remains
what makes one. A plan is derived from a bootstrap report and **from nothing else**,
so `plan` and `check` cannot disagree about a host -- and `plan` is read-only *by the
layer contract*, because the planner is in `domain` which may perform no I/O.

**One module in the package may now start a process**, and it is named in both
directions by `tests/architecture/test_process_discipline.py`. The layer contract
needed no edit -- `subprocess` was always I/O-capable and adapters always could
perform I/O -- so this is an unbroken property becoming a bounded one. Writing that
rule wrong first is recorded: a bare attribute check flagged `HostFacts.system` in
seven modules that start nothing.

**An action declares who performs it**, and the wheel is why: it holds `globin/` and
its `.dist-info` and nothing else, so an installed GLOBIN has no `tools/` to invoke.
What GLOBIN cannot do is reported with the exact command that can.

**No fifth status word, no twenty-sixth exit code, no `verify` verb.** `UNMEASURED`
already means what `BLOCKED` means, an incomplete environment is honestly `12`, and
`bootstrap preflight` already runs every check and gates -- typing `verify` names the
replacement. **26 stays free.**

The band closure delivered the **granularity review** `ROADMAP.md` and six ADRs had
been holding for this phase. Its finding is arithmetic: across thirteen scored
amendments *nothing deferred* is met 13/13 and *no phase owns the work* 1/13, so two
of the four conditions carry almost no information. And the band is not drawn wrong
-- **a subject is missing**: sixteen rows describe provisioning steps while eleven
phases delivered the runtime substrate, for which the band has no rows at all.

Phase 033 opened the venue band, and gave GLOBIN somewhere to write down what
Binance documents.

```bash
.venv\Scripts\globin.exe api-reality show
```

```bash
python -m tools.quality venue
```

The registry is **one declared document**,
[`docs/engineering/binance-api-reality.toml`](docs/engineering/binance-api-reality.toml),
and **no venue host is spelled anywhere in the package** --
`tests/architecture/test_api_reality_discipline.py` fails if one appears. That rule
can be that strong because product families, environments, key permissions and
schema families are **data rather than enumerations**: the identifier discipline
refused the first draft, and it was right, because which products a venue offers
changes without GLOBIN being redeployed.

**Six status words, and the one that matters is `unknown`.** *Not documented* and
*documented absent* are different facts; 56 rows carry `unknown` against 51
`supported`, and **`unsupported` appears zero times** because that word claims a
document states an absence and none does. `EvidenceKind.OBSERVED` exists and
**nothing may write it** -- GLOBIN has never contacted the venue, and a contract
test enforces by assertion what `VerificationState` enforces by omission.

**Demo and testnet are separate kinds**, with the semantics Binance tabulates, and
each non-production environment declares the substring its hosts are spelled with --
so a live host filed as paper is refused structurally rather than by review.

**The gate is a second reader.** Nothing under `tools/` imports `globin`, so the two
parse the same document with no shared code, and a contract test compares what they
see. `refresh` reaches the network and lives outside the package deliberately:
`src/globin` still opens **no outbound connection**, and Phase 045 is where it earns
one. **No new exit code** -- 26 stays free.

**Three of Binance's four machine-readable lifecycle files are not valid JSON**,
measured rather than remembered. Each is marked `known_unparseable`, and a source
declared unparseable that *starts* parsing also fails, so the exemption cannot
outlive its reason. The derivatives documentation has **no admissible route at
all** -- it is client-rendered, and `SOURCE_POLICY.md` forbids both scraping it and
accepting a generated summary in its place. Every non-Spot endpoint is therefore
`unknown`, which is the honest answer rather than a gap.

---

## Test expectations

Write tests alongside behaviour, never afterwards. Test meaningful invariants,
not whole-file snapshots — a test that fails on every editorial improvement
trains people to update expectations without reading them.

The suite exists to make policy enforceable. It asserts project identity, the
master-only branch rule, the 320-phase structure, the absence of runtime
dependencies, the presence and consistency of required documentation, that
every repository-relative Markdown link resolves, that no credential-shaped
file would be committed, and that tool configuration is not duplicated outside
`pyproject.toml`.

Since Phase 5 it also enforces the conditions it runs under. Every test is
offline — an autouse fixture refuses outbound sockets — and every test must leave
the environment and working directory as it found them, or it fails. Use
`monkeypatch.setenv` and `monkeypatch.chdir` rather than changing either
directly. Where a mock is genuinely right, it must be
`create_autospec(..., spec_set=True)`; the default remains a hand-written double
satisfying a `Protocol`. Write a property test when a real invariant exists, not
for every change.

---

## Source policy in brief

Never invent an endpoint, parameter, error code or library signature. Consult
current primary documentation and record it in `docs/research/`. Official
Binance documentation is authoritative for Binance; upstream project
documentation is authoritative for libraries.

Scraping Binance, parsing its pages, or calling undocumented private endpoints
is prohibited without exception.

---

## Git in brief

All work happens on `master`. Verify, inspect the staged diff for secrets,
commit with a message naming the phase, push to `origin/master`, then confirm
local and remote match and the tree is clean. Full procedure in
[`docs/GIT_WORKFLOW.md`](docs/GIT_WORKFLOW.md).

---

## Phase discipline

Implement the current phase. Not the next one.

Premature implementation is a defect, not initiative: it bypasses the design
work that the later phase was created to do, and it produces code that no test
or document yet describes. If you believe a phase boundary is wrong, say so —
but do not resolve it unilaterally by building ahead.

Equally, do not leave the current phase partly done. Finish it, and state
plainly anything you could not complete.

---

## Reporting

Report evidence rather than assurance: the exact commands you ran, their
results, the commit hash, whether the push succeeded, and anything you could not
verify. Never describe a check as passing unless you ran it and saw it pass.
