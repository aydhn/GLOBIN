# ADR-0053 — Drift is measured against an accepted baseline, and repair is a declared classification rather than an inferred one

## Status

Accepted — Phase 019.

## Context

Phase 017 declared the runtime contract, built `.venv` from it, and gave the
repository `tools/quality/runtime/` to check one against the other. That answers
an absolute question: *is this machine acceptable?*

It cannot answer the question Phase 019 is assigned, because that one needs two
measurements. `ROADMAP.md` line 152 reads: *"Detect divergence from the runtime
contract as it appears, and define repair short of recreating the environment."*
"As it appears" is a claim about time, and a contract has no time in it.

The gap is not theoretical, and it is widest exactly where the contract is
deliberately loose:

- `minimum_patch` is a **floor**, by a decision `runtime-contract.toml` argues at
  length: "An exact pin would fail the build on the day a security patch was
  installed, which is the day it is least welcome." So an interpreter whose patch
  went *backwards* still satisfies the contract, and `runtime` passes on it.
- A `PIP_INDEX_URL` appearing in the environment redirects every install this
  project makes and violates no contract at all.
- A machine-wide `pip.ini` appearing does the same.
- A quality tool drifting past the version the workflows pin is how a local gate
  starts disagreeing with continuous integration with no diff to explain it —
  Phase 004 found that class of fault between the pre-commit hook and CI, which is
  why those two are already compared.

Three delivered documents had recorded this as outstanding and named the phase:
`QUALITY_GATES.md`, `RUNTIME_BASELINE.md` and `FOUNDATION_ACCEPTANCE.md`.

There is a second, sharper problem. `RUNTIME_BASELINE.md` documents five distinct
`.venv` faults and prescribes **the same destructive remedy for all five**:
"Rebuild with `-Recreate`". They are not equally bad. One of them is a single key
in a text file that the interpreter re-reads on every start. Answering it by
destroying the environment is the advice this phase exists to correct, and
"repair short of recreating the environment" is precisely that correction.

## Decision

### 1. Drift is a separate gate, in its own package

`tools/quality/drift/`, in the six-file shape every gate here uses, with its own
manifest (`globin.drift.manifest`), its own closed `DRIFT_*` reason set and its
own evidence directory.

Not more subcommands on `tools/quality/runtime/`. That package's manifest declares
`PHASE = 17` and a `REASONS` frozenset whose every member is `RUNTIME_*`; folding
drift findings into it would either misreport the phase or force a schema bump on
a document Phase 017 published and CI uploads. The repository's unit is one
package, one manifest, one question, and there are nine precedents.

### 2. The observation is imported, never re-implemented

`observe_interpreter`, `observe_host`, `observe_environment`, `observe_pip`,
`recorded_path`, `parse_pyvenv_cfg`, `parse_version` and `Version` are Phase 017's
and are called. Phase 018 set the precedent for reading another gate's contract
rather than restating it, and the reasoning transfers: a second copy of an
observation is a second thing to keep in step, and the two would disagree on
exactly the day it mattered.

### 3. The baseline is a previous measurement, held outside the tree

`runtime-contract.toml` states why it is not a snapshot: "a manifest generated
from the host could only ever agree with the host, which is a mirror rather than a
check." A **committed** drift baseline would be that mirror. So the baseline is a
previous observation, in the gitignored `.globin/drift/` — which is also the only
scope on which "what this host used to be" means anything.

### 4. A baseline is accepted deliberately, and `check` never writes one

`drift accept` records; `drift check` compares and records nothing. A check that
recorded whatever it found would certify its own observation, and drift would be
undetectable by construction: every run would accept the state the previous run
had drifted into.

### 5. With no baseline the verdict is unmeasured, not clean

A fresh clone exits `3`. `DEPENDENCY_POLICY.md` prohibits conflating "could not
look" with "looked and found nothing" by name, and the three-valued verdict
vocabulary exists so the two never share a colour. This is also why `drift` is in
neither `fast` nor `full`: it would be red on every fresh clone, and a gate that is
red on a tree nobody has touched is a gate people learn to ignore.

### 6. The observation is flat, and its values are text

Dotted keys to strings. A nested comparison would have to answer whether a changed
table is one difference or several, and every answer to that surprises somebody —
`globin.domain.configuration` refuses the same thing for the same reason. Text
because the observation crosses JSON between runs, where `True` and `"True"` are
different values meaning the same thing.

### 7. Repair is a classification the policy declares, and the gate obeys

`docs/engineering/drift-policy.toml` gives each observation key a severity and one
of five repair verdicts. The gate reads `repair` from the file and will not act on
anything not marked `in-place`. The file therefore changes what the tool does
rather than describing what it already did — the same relationship
`runtime-contract.toml` has to `tools/quality/runtime/`.

**`bootstrap` and `recreate` are separate verdicts**, and that separation is the
phase's subject. `bootstrap.ps1` is idempotent and removes nothing unless
`-Recreate` is passed.

### 8. Every declared verdict is recomputed from the evidence beside it

ADR-0052's pattern, applied to repair rather than to wheels. A class claiming a
fault is repairable in place must declare what the repair does and where it
writes; one claiming anything else must declare no action and write nowhere. An
entry that does not agree with itself fails offline, without a host.

### 9. One severity is conditional, and its rule is named

`interpreter.version`, under `interpreter-version`: forward on the contracted line
is **benign**, backward is **material**, a different line is a **violation**. A
benign judgement carries no repair whatever its class declares — offering to
correct a forward patch would be offering to undo a security fix. Failing on a
forward patch would reinstate the exact pin the contract refused.

### 10. Repair writes inside the environment and nowhere else

ADR-0050's boundary is not widened. The check that permits a write is a pure
function with its own tests, on the pattern of `runtime.plan.deletion_problems`,
and `tests/contract/test_drift_contract.py` reads this package's source and fails
on `winreg`, `setx`, `Set-ExecutionPolicy`, `HKEY_`, `os.putenv` and
`shutil.rmtree`. A machine-wide `pip.ini` and a `PIP_*` variable are **reported and
never touched**.

### 11. There is exactly one in-place repair, and it is sourced

`include-system-site-packages` in `pyvenv.cfg`. PEP 405 specifies that the file is
scanned when the interpreter launches, and the `site` module's documentation
states that where the key is true "the system-level prefixes will be searched for
site-packages, otherwise they won't". So the value is read afresh on every start
and rewriting it takes effect on the next one. Both are recorded in
`docs/research/phase_019_sources.md`. A contract test pins the count at one, so
growing it is an edit somebody has to make deliberately.

### 12. No dependency was added to build this

`project.dependencies` is still empty. `tomllib`, `hashlib`, `json`, `pathlib` and
`importlib.metadata` are the standard library.

## Consequences

**Good.** The repository can now tell "this machine is acceptable" from "this
machine is what it was", and the second question is the one that explains a gate
that started failing on Tuesday. Five faults that were all answered with "rebuild"
are now four, and the one that moved is corrected without destroying anything.
The classification is reviewable in a diff rather than buried in a function, and
it is recomputed rather than believed. Continuous integration gains a cross-process
determinism claim it did not have: `accept` then `check` on a machine with no
history fails if any recorded value is unstable between two processes.

**Costs, accepted.** A developer must run `drift accept` once, and again after any
change they meant to make. That is real friction and it is the price of the
guarantee in decision 4 — a baseline nobody accepted is a baseline that certifies
whatever happened. The gate is unmeasured until they do, which will surprise
somebody the first time; the finding says what to run. The policy is one more
file to keep in step with reality, and an observation key nobody classifies fails
the gate rather than passing quietly — deliberately, because the alternative is
that the day a new key starts moving is the day coverage silently stopped.

**What this does not decide.** Dependency resolution and locking remain Phase
020's: nothing here runs a resolver, writes a lockfile or claims a transitive
tree. Which distributions GLOBIN depends on at runtime is Phase 021's. Where
configuration files live and which sources are consulted in what order remain
Phases 026 and 027's. This gate compares the installed version of a tool this
repository already declares against a pin it already declares, and comparison is
not resolution.

## Alternatives Considered

**Subcommands on `tools/quality/runtime/`.** Rejected — see decision 1. The
manifest and the reason vocabulary are the deciding objections, not the file
count.

**Reusing `.globin/runtime/runtime-manifest.json` as the baseline.** Rejected, and
this was the closest call. It is written by another gate on **every run**, so "the
previous state" would be whatever the last check saw — which detects drift only
between two adjacent invocations, and not at all on the second consecutive run. It
would also freeze Phase 017's schema, since a reader here would refuse a version
it does not implement.

**Comparing only against the contract, with no baseline.** Rejected — that is what
`runtime` already does, and it is exactly the gate that passes on a backward patch.

**Recording the baseline automatically on first check.** Rejected. It removes the
friction in *Costs* above and removes the guarantee with it: a check that records
what it finds is a check that agrees with itself.

**Treating an absent baseline as benign so `full` could run the gate.** Rejected —
decision 5. It is the "could not look" / "found nothing" conflation, and it would
have let the gate into `full` by making it dishonest.

**Inferring the repair from the code rather than declaring it.** Rejected. The
classification is a judgement about risk, not a computation, and a judgement that
lives only in a function is one nobody reviews.

**Repairing a moved environment by regenerating the console scripts.** Rejected on
the evidence: `venv`'s documentation states environments are "not considered as
movable or copyable" and that the remedy is to recreate at the target location.
Shipping a repair against a documented non-guarantee would be inventing behaviour.

**Performing the toolchain reinstall inside `drift repair`.** Rejected — it
reaches an index, and this gate must work on an aeroplane. The verdict is
`bootstrap`, and `bootstrap.ps1` already installs those pins.

## Risks and Trade-offs

**A developer accepts a baseline on an already-drifted machine.** Then the drift
is frozen as correct and the gate reports nothing. This is inherent to any
baseline, and the mitigation is that `runtime` still answers the absolute question
independently: a machine outside the contract fails there whatever `drift` has
accepted. Observable signal — `runtime` failing while `drift` passes.

**The policy falls behind the observation.** A key the host reports and the policy
does not classify fails the gate, which is the correct direction but arrives as a
surprise. `tests/integration/test_drift_end_to_end.py` compares the two on this
machine on every run, so the disagreement is normally found in the suite rather
than in the gate. Confidence here is high.

**The one in-place repair rests on a documented behaviour that could change.** If
a future CPython stopped re-reading `pyvenv.cfg` at start-up, the repair would
edit a file nothing reads and report success. Two independent primary sources are
recorded, and the observable signal is sharp: `drift repair` would report a repair
performed and the following `check` would still show the same difference, because
the gate re-measures after repairing rather than assuming.

**`importlib.metadata` reports what is importable, which is not always what is
installed.** A tool shadowed on `sys.path` could be reported at the shadowing
version. The scope limits the damage — only distributions this repository declares
by name are read — and the direction of failure is a false report rather than a
missed one. Confidence here is moderate, not high.

**The baseline is per-machine and ignored by Git**, so nothing about it is shared
or reviewed. That is deliberate — it is an observation, and observations are not
promoted to declarations — but it means two developers can hold different
baselines and see different results. The contract, which is committed, is what
they share.

## References

- [ADR-0050](0050-the-runtime-is-a-declared-contract-and-venv-is-its-only-environment.md)
  — the contract this compares against, and the boundary this does not widen
- [ADR-0052](0052-wheel-availability-is-a-recorded-survey-whose-verdict-is-recomputed.md)
  — the recompute pattern, applied here to repair
- [ADR-0045](0045-a-platform-capability-is-a-recorded-state-never-a-pass.md) — a
  recorded state is never a pass, which is what an absent baseline is
- [ADR-0024](0024-tests-are-offline-and-isolated-by-construction.md) — why this
  gate reaches nothing and needs no injected fetcher
- [`../engineering/ENVIRONMENT_DRIFT.md`](../engineering/ENVIRONMENT_DRIFT.md) —
  what the declaration only states
- [`../engineering/drift-policy.toml`](../engineering/drift-policy.toml) — the
  classification itself
- [`../research/phase_019_sources.md`](../research/phase_019_sources.md) — the
  sources decision 11 rests on
- `https://peps.python.org/pep-0405/` — `pyvenv.cfg` is scanned at interpreter
  launch
- `https://docs.python.org/3/library/site.html` — the flag is re-read under a
  virtual environment
- `https://docs.python.org/3/library/venv.html` — environments are not movable or
  copyable

## Supersedes

Nothing. This is the first record about detecting divergence over time. The record
that decided what the environment must be is cited under *References* and is
unchanged by this one; that decision says what a correct machine looks like, and
this one says how to notice that a machine stopped being it.

## Superseded By

Nothing yet.
