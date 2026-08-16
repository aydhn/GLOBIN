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
| Is the foundation band complete, and on what evidence? | [`docs/release/FOUNDATION_ACCEPTANCE.md`](docs/release/FOUNDATION_ACCEPTANCE.md), [`docs/engineering/foundation-acceptance.toml`](docs/engineering/foundation-acceptance.toml) |
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
`tmp` — which is deliberately *not* `.globin/`: that tree is evidence about this
repository, read by CI, and this one is state about this machine. **No secret, no
credential and no bulk data goes in either.** Every small document is published
atomically, and one coordinator per machine is guaranteed by an operating-system
lock whose *acquisition* decides ownership — **the lock file's existence proves
only that GLOBIN once ran**, so a stale one never blocks a start-up and is never
deleted on a guess. `doctor` probes that lock and does not keep it. What is
guaranteed on each kind of ending, and what is not, is in
[`docs/engineering/RUNTIME_FILESYSTEM.md`](docs/engineering/RUNTIME_FILESYSTEM.md).

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
