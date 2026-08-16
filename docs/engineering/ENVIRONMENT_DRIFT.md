# Environment Drift

How GLOBIN notices that the machine stopped being the machine its gates were
measured on, and what it does about each way that happens.

Phase 017 declared the runtime contract and built the environment;
[`RUNTIME_BASELINE.md`](RUNTIME_BASELINE.md) is that document and remains the
authority on what this host must be. This one is about a different question.

---

## Why a second gate, when `runtime` already checks the host

`runtime` asks **is this machine acceptable?** It compares the host against
[`runtime-contract.toml`](runtime-contract.toml) and answers from the contract
alone. That question has one measurement in it.

`drift` asks **is this machine what it was?** That question needs two, and the
second one is a *previous* answer. The two gates disagree in exactly the places
where a contract is looser than reality:

| Situation | `runtime` | `drift` |
|---|---|---|
| The interpreter's patch advanced within the contracted line | passes | benign, and says so |
| The interpreter's patch went **backwards**, still above the floor | passes | **material** |
| A `PIP_INDEX_URL` appeared in the environment | passes | **material** |
| A machine-wide `pip.ini` appeared | passes | **material** |
| A tool was upgraded past the version CI pins | passes | **material** |

None of those violate the contract. `minimum_patch` is a floor by deliberate
decision — an exact pin would fail the build on the day a security patch was
installed — and nothing in the contract mentions an index or a tool version. They
are all changes somebody made to the machine, and the first four are invisible
until something else breaks and nobody can say what moved.

---

## The baseline is accepted, not assumed

```bash
python -m tools.quality.drift accept
```

This records the current host as the state you are willing to be held to. It
writes `.globin/drift/drift-baseline.json`, which is ignored by Git and local to
this machine — which is the only scope on which "what this host used to be" means
anything.

```bash
python -m tools.quality drift
```

This compares and reports. **It never records a baseline.** A check that recorded
whatever it found would certify its own observation, and drift would be
undetectable by construction: every run would accept the state the previous run
had drifted into.

**With no baseline the verdict is `unmeasured`, not `passed`.** That is the state
of a fresh clone, and it exits `3`. "Could not look" and "looked and found
nothing" are different facts, and
[`../DEPENDENCY_POLICY.md`](../DEPENDENCY_POLICY.md) prohibits conflating them by
name — the three-valued verdict vocabulary exists so they never share a colour.

After a change you meant to make, accept again. That is the whole workflow.

---

## What is recorded, and what is deliberately not

The observation is a flat set of dotted keys, taken with Phase 017's own
functions rather than a second copy of them. Five areas: `host`, `interpreter`,
`environment`, `pip` and `toolchain`.

**No path outside the repository is ever written down.**
`tools/quality/runtime/plan.py::recorded_path` renders one as a fingerprint, and
a path inside the repository as a relative path. Every absolute path on a Windows
development host contains the account holder's name, and `.globin/` is uploaded
by continuous integration to a public repository.

**No configuration value is ever read.** For `pip` the gate records *which*
configuration scopes exist and *which* `PIP_*` variables are set, by name. It does
not read what any of them says. An index URL is the single most likely place in
this system for a credential to appear, and the way to keep one out of a published
artefact is not to read it.

Both documents this gate writes are scanned for secret-shaped content before they
are written, and refused if any is found.

---

## The classification

[`drift-policy.toml`](drift-policy.toml) declares, per observation key, how
serious a change is and what would put it right. It is written by a person and
nothing generates it — a classification derived from the host could only agree
with the host, which is a mirror rather than a check.

**The file is obeyed, not described.** The gate reads `repair` from it and will
not act on anything it does not mark `in-place`. Editing a line changes what the
tool does.

### Severity

| Severity | Means |
|---|---|
| `violation` | The change has taken the environment outside the runtime contract |
| `material` | Real and worth acting on; the contract still holds |
| `benign` | The value is expected to vary and its variation means nothing |
| `conditional` | Which of the above applies depends on the values, and a named rule decides |

One class is `conditional` today: `interpreter.version`, under the
`interpreter-version` rule. Forward on the contracted line is benign, backward is
material, a different line is a violation. A benign judgement carries no repair,
whatever its class declares — offering to correct a forward patch would be
offering to undo a security fix.

### Repair

| Verdict | Means | Who acts |
|---|---|---|
| `in-place` | A bounded action inside the environment corrects it | **The tool**, on `drift repair` |
| `bootstrap` | Re-running `bootstrap.ps1` corrects it, destroying nothing | You |
| `recreate` | Nothing short of rebuilding the environment corrects it | You, with `-Recreate` |
| `operator` | Something outside the repository must change | You |
| `none` | There is nothing to correct | Nobody |

`bootstrap` and `recreate` are separate verdicts, and that separation is this
phase's subject. `bootstrap.ps1` is idempotent and removes nothing unless
`-Recreate` is passed, so a drifted toolchain is restored by re-running it rather
than by destroying the environment.

Every verdict is recomputed from the evidence recorded beside it. A class claiming
a fault is repairable in place must also declare what the repair does and where it
writes; one that does not agree with itself fails offline, without a host.

---

## Repair, and the boundary it does not cross

```bash
python -m tools.quality.drift repair
```

It measures first — repairing without measuring is repairing a guess — performs
the repairs the policy marks `in-place`, then measures again and records what
remains. **It does not accept a new baseline.** A repair that re-recorded the
baseline would be certifying its own work.

**It writes only inside the project environment.** ADR-0050 draws that boundary
and this gate does not widen it: nothing here edits the registry, `PATH`, the
execution policy, or any interpreter outside `.venv`. The check that permits a
write is a pure function with its own tests, and
`tests/contract/test_drift_contract.py` reads this package's source and fails on
the constructs that would cross the line.

### The one repair, and why it is a repair at all

`environment.system_site_packages` — the environment has gained access to the
machine's global packages, which makes its contents depend on the machine it
happens to be on.

`RUNTIME_BASELINE.md` currently answers this with "rebuild with `-Recreate`",
alongside four other faults that genuinely need it. This one does not.
`pyvenv.cfg` is read at interpreter **start-up**, not consulted once at creation:
PEP 405 specifies that the file is scanned when the interpreter launches, and the
`site` module's documentation states that where `include-system-site-packages` is
true "the system-level prefixes will be searched for site-packages, otherwise
they won't". So rewriting that one key takes effect on the next run. Sources are
recorded in [`../research/phase_019_sources.md`](../research/phase_019_sources.md).

The repair rewrites that key and nothing else — in particular not `home`, which
records which interpreter built the environment.

### What repair refuses, and why

| Refused | Reason |
|---|---|
| Unsetting a `PIP_*` variable | Outside the repository; a tool that edited the environment would be reconfiguring the machine it was asked to describe |
| Removing a machine-wide `pip.ini` | Outside the repository, and shared with every other project on the host |
| Creating or deleting `.venv` | That is `bootstrap.ps1`'s, and the recursive-delete guard lives in `tools/quality/runtime/` where Phase 017 put it |
| Installing anything | Reaches the index, and this gate must work on an aeroplane |
| Changing the interpreter, `PATH` or the execution policy | ADR-0050 |

---

## Diagnosing each finding

Every finding names the key, both values and the repair verdict. This is what to
do about the ones that need a person.

- **`interpreter.version` — material.** The interpreter went backwards on the
  contracted line. Something reinstalled or downgraded Python. Check with
  `where python`, install a patch at or above the recorded one, and accept again.
- **`interpreter.version` — violation.** The minor line changed. The environment
  is bound to the interpreter that built it; rebuild with
  `bootstrap.ps1 -Recreate` from an interpreter the contract accepts.
- **`environment.location.*`.** The environment or a directory above it was moved
  or copied. `venv`'s documentation is explicit that environments are not movable;
  recreate at the new location and delete the old one.
- **`environment.base_present` / `created_from`.** The installation the
  environment was built from is gone or is a different one, usually because Python
  was upgraded in place. Rebuild with `-Recreate`.
- **`pip.config.*` / `pip.overrides`.** A pip configuration source or a `PIP_*`
  variable appeared. Decide whether you meant it. If you did, accept a new
  baseline; if you did not, remove it yourself — the gate will not.
- **`pip.belongs_to_running_interpreter`.** `pip install` would write outside this
  environment. Run through `.venv\Scripts\python.exe`. **Never use a global
  `pip install` for this project**: it installs for every project at once, and
  nothing records that it happened.
- **`toolchain.*`.** A quality tool is at a different version than the workflows
  pin. This is how a local gate starts disagreeing with CI with no diff to explain
  it. Re-run `bootstrap.ps1`.
- **`host.*`.** Windows changed. Nothing here can act on that; accept a new
  baseline once you have decided the machine is still the one you meant.

An unclassified key fails the gate rather than passing quietly. If a new
observation key appears, decide what it means and add a class — the alternative is
that the day it starts moving is the day coverage silently stopped.

---

## What this gate is not, since Phase 020

Phase 020 added `python -m tools.quality.lock installed`, which also compares this
environment against a written record. The two are not redundant and they are not
interchangeable.

**This gate asks whether the machine is what it *was*.** Its record is a baseline
somebody accepted with `drift accept`, and with no baseline it is `unmeasured`
rather than clean. **The lock gate asks whether the environment is what the
repository *declares*.** Its record is a committed file, and Git is the
acceptance. Folding one into the other would make a single exit code mean two
kinds of thing.

The scopes differ too, deliberately. `observe_toolchain` reads only the tools this
repository declares by name; the lock covers all forty-nine distributions those
tools resolve to. Widening this gate to match would break the boundary it
documents about itself, and would make `drift accept` record a baseline of the
whole of `site-packages`.

Neither subsumes the other in practice: this catches a tool moving on the host
between two accepted baselines even when the lock is stale, and the lock gate
catches a transitive package no baseline ever covered.

---

## What this does not cover

| Question | Owning phase |
|---|---|
| Which distributions GLOBIN depends on at runtime | 021 |
| Where configuration files live, and what profiles exist | 026 |
| Which configuration sources are consulted, and in what order | 027 |

This gate runs no resolver, writes no lockfile and claims no transitive tree. It
compares the installed version of a tool this repository already declares against
the pin it already declares, and comparison is not resolution.
