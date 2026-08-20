# Environment band acceptance

What Phases 017-032 had to satisfy before the environment band could be frozen,
and what answers each requirement.

The machine-readable half is
[`../engineering/environment-acceptance.toml`](../engineering/environment-acceptance.toml),
which `python -m tools.quality release` reads and
`tests/contract/test_release_contract.py` compares against the tree in both
directions. This document is the half a person reads.

It is the second of twenty such records. The first is
[`FOUNDATION_ACCEPTANCE.md`](FOUNDATION_ACCEPTANCE.md), which certified Phases
001-016 and was frozen as `v0.1.0`; everything it says about what a band
acceptance record *is* applies here and is not repeated.

---

## What this certifies, and what it does not

That a Windows machine can be turned into a reproducible GLOBIN host, and that
each step of doing so is checkable rather than asserted. The chain, end to end: a
**declared host and interpreter**, a **virtual environment** built from a verified
base and repaired against an accepted baseline, **locked dependencies** whose
every claim is recomputed, a **verified numerical stack**, **detected GPU
capability** and measured benefit, an **application bootstrap** that refuses
fail-closed, a **runtime filesystem** with one coordinator, **diagnostics, health,
a watchdog, telemetry and a loopback endpoint**, **typed configuration** that
explains itself, **secret custody** in two mechanisms disjoint by arithmetic, and
a **degradation posture** folded from what each factory actually returned.

**It does not certify that GLOBIN trades, or has ever contacted Binance.** It has
not. Nothing in this band reaches a venue, and `VerificationState` still has no
member meaning *confirmed* because there is nothing to confirm against.

**It does not certify that GLOBIN holds a credential.** It holds none. It has two
places to put one, which is a different sentence.

**It does not certify that the phase boundaries were right.** That question is
[`../engineering/GRANULARITY_REVIEW.md`](../engineering/GRANULARITY_REVIEW.md)'s,
and its answer is *not entirely*.

---

## Status vocabulary

Four words, unchanged from the foundation matrix.

| Status | Meaning |
|---|---|
| `PASS` | Met, with evidence that exists. |
| `FAIL` | Not met. A blocking criterion in this state stops a release. |
| `BLOCKED` | The answer depends on something outside this repository. **Never a pass** — the gate maps it onto the unmeasured verdict, which [ADR-0045](../adr/0045-a-platform-capability-is-a-recorded-state-never-a-pass.md) established outranks a failure. |
| `NOT_APPLICABLE` | Genuinely out of scope, with the reason recorded. |

There is deliberately no `WARN`. A warning has no release semantics until
somebody writes them down, and the semantics it acquires in practice are
"proceed anyway".

---

## Result

**61 criteria across thirteen categories. 51 are blocking.**

| Status | Count |
|---|---|
| `PASS` | 60 |
| `FAIL` | 0 |
| `BLOCKED` | 1 |
| `NOT_APPLICABLE` | 0 |

**Every blocking criterion passes.** The single `BLOCKED` criterion is
`ENV-F-04`, CUDA benefit measured on a device, which is non-blocking and is
discussed under *Unresolved* below.

Identifiers are `ENV-<letter>-<NN>`, where the letter is the category's position:
`A` for the first through `M` for the thirteenth. The gate checks that the letter
and the category agree, because two spellings of one fact need a check that they
do not disagree quietly.

**Why the categories are not one per phase.** The foundation matrix runs one
category per phase because that band's rows described its work. This band's did
not: sixteen roadmap rows describe provisioning steps, while eleven consecutive
phases delivered those *and* the running application's substrate, for which the
band has no rows at all. A matrix organised by phase would encode that defect and
read as a second roadmap. These thirteen are capability groups, and several draw
on four phases at once — `runtime-observability` alone answers for Phases 023
through 027.

---

## The matrix

Every criterion, its requirement, whether it blocks a release, and its status.
The reasoning behind each is in the declaration; this table is the index, and
`test_release_contract.py` compares the two in both directions.

### A — Host baseline

| ID | Requirement | Blocking | Status |
|---|---|---|---|
| `ENV-A-01` | The supported host and interpreter are declared once, machine-readably. | yes | `PASS` |
| `ENV-A-02` | The host's capabilities are separated from the contract it satisfies. | yes | `PASS` |
| `ENV-A-03` | Native processor architecture is measured through the only API that can tell it apart from the process's. | yes | `PASS` |
| `ENV-A-04` | The compatibility fingerprint excludes volatile fields by type rather than by denylist. | no | `PASS` |

### B — Environment lifecycle

| ID | Requirement | Blocking | Status |
|---|---|---|---|
| `ENV-B-01` | The project environment is built deterministically from a verified interpreter. | yes | `PASS` |
| `ENV-B-02` | Automation never depends on activating the environment. | yes | `PASS` |
| `ENV-B-03` | Divergence from the contract is detected against an accepted baseline, and repair is a classification rather than an action. | yes | `PASS` |
| `ENV-B-04` | Exactly one fault is repaired in place, and the repair writes only inside the environment. | no | `PASS` |
| `ENV-B-05` | The recursive delete that recreation implies cannot be aimed at anything but the declared environment. | yes | `PASS` |
| `ENV-B-06` | What would be changed is shown before anything is changed, and showing it changes nothing. | yes | `PASS` |
| `ENV-B-07` | An interrupted provisioning run cannot be mistaken for a finished one. | yes | `PASS` |
| `ENV-B-08` | Applying the same plan twice changes nothing the second time. | no | `PASS` |
| `ENV-B-09` | Exactly one module in the package may start a child process, and it is named. | yes | `PASS` |
| `ENV-B-10` | What GLOBIN cannot perform is reported with the command that can, rather than attempted. | yes | `PASS` |

### C — Dependency locking and distribution

| ID | Requirement | Blocking | Status |
|---|---|---|---|
| `ENV-C-01` | Every dependency is resolved and hash-pinned, and the lock's claims are recomputed rather than believed. | yes | `PASS` |
| `ENV-C-02` | No dependency is declared without a written review. | yes | `PASS` |
| `ENV-C-03` | The running application can see which versions are installed, not merely which distributions. | yes | `PASS` |
| `ENV-C-04` | A packaging build produces installable artefacts, and they were installed rather than inspected. | no | `PASS` |

### D — Dependency materialization

| ID | Requirement | Blocking | Status |
|---|---|---|---|
| `ENV-D-01` | Every library the programme schedules is known to have a wheel for the pinned interpreter, or its gap is owned. | yes | `PASS` |
| `ENV-D-02` | Whether the lock could be installed offline is answerable without a network, and the fallback is unreachable rather than un-taken. | yes | `PASS` |
| `ENV-D-03` | The clean room used to test an install cannot touch the developer's environment. | yes | `PASS` |
| `ENV-D-04` | The second PEP 751 reader is the specification's own implementation, not a second hand-written parser. | no | `PASS` |

### E — Scientific stack

| ID | Requirement | Blocking | Status |
|---|---|---|---|
| `ENV-E-01` | The installed numerical stack is verified to compute correctly, not merely to be present. | yes | `PASS` |
| `ENV-E-02` | Verifying a library is not adopting it. | yes | `PASS` |
| `ENV-E-03` | The native TA-Lib question was measured on this host rather than read off a filename. | no | `PASS` |

### F — GPU capability

| ID | Requirement | Blocking | Status |
|---|---|---|---|
| `ENV-F-01` | GPU presence, driver, compute capability and CUDA availability are detected without assuming any of them. | yes | `PASS` |
| `ENV-F-02` | The GPU contract declares an interface and never a baseline. | no | `PASS` |
| `ENV-F-03` | Whether a workload benefits from a GPU is measured, and a timing is not treated as evidence of reproducibility. | no | `PASS` |
| `ENV-F-04` | A CUDA workload's benefit is measured on a device rather than asserted. | no | `BLOCKED` |

### G — Application bootstrap

| ID | Requirement | Blocking | Status |
|---|---|---|---|
| `ENV-G-01` | One entry point decides whether a GLOBIN process may start, and refuses fail-closed when it may not. | yes | `PASS` |
| `ENV-G-02` | Every failure class has one exit code, declared once, and the earliest failure is the one reported. | yes | `PASS` |
| `ENV-G-03` | Every preflight check declares whether its answer survives the run. | yes | `PASS` |
| `ENV-G-04` | The bootstrap evidence is deterministic and carries no secret. | yes | `PASS` |

### H — Runtime filesystem and lifecycle

| ID | Requirement | Blocking | Status |
|---|---|---|---|
| `ENV-H-01` | A running GLOBIN's mutable state is user-local and separate from the repository's evidence. | yes | `PASS` |
| `ENV-H-02` | One coordinator per machine is guaranteed by an acquisition, never by the presence of a file. | yes | `PASS` |
| `ENV-H-03` | Every small document is published atomically, and shutdown reaches a fixed order whatever the application did. | yes | `PASS` |

### I — Runtime observability

| ID | Requirement | Blocking | Status |
|---|---|---|---|
| `ENV-I-01` | The only area appended to is bounded by a validated policy rather than trusted. | yes | `PASS` |
| `ENV-I-02` | A measurement that was not taken is never reported as zero. | yes | `PASS` |
| `ENV-I-03` | A support bundle is redacted, self-validating and built from an allowlist. | yes | `PASS` |
| `ENV-I-04` | A heartbeat cannot be satisfied by a component looping inside a wedged call. | yes | `PASS` |
| `ENV-I-05` | Metric cardinality is arithmetic rather than a hope, and export is off by default as an object graph rather than a flag. | yes | `PASS` |
| `ENV-I-06` | The diagnostics surface is loopback-only by a type that cannot hold anything else, and read-only. | yes | `PASS` |

### J — Configuration resolution

| ID | Requirement | Blocking | Status |
|---|---|---|---|
| `ENV-J-01` | Given a layout and a profile, the candidate documents are a pure function of the two. | yes | `PASS` |
| `ENV-J-02` | Precedence is declared, and the whole order follows one rule. | yes | `PASS` |
| `ENV-J-03` | Configuration explains itself through two fingerprints, and comparison reads digests rather than displays. | yes | `PASS` |
| `ENV-J-04` | The preflight validates what a run will actually use rather than the declared defaults. | yes | `PASS` |

### K — Secret custody

| ID | Requirement | Blocking | Status |
|---|---|---|---|
| `ENV-K-01` | A secret reference is ordinary data and a secret value has no string form. | yes | `PASS` |
| `ENV-K-02` | The platform's silent collision is closed by one key builder. | yes | `PASS` |
| `ENV-K-03` | Rotation is constructed rather than inherited from the platform. | yes | `PASS` |
| `ENV-K-04` | Collection is interactive only, and a value that cannot be collected safely never exists. | yes | `PASS` |
| `ENV-K-05` | A capability is a recorded state, and no member of the vocabulary means confirmed. | yes | `PASS` |
| `ENV-K-06` | The two secret mechanisms are disjoint by arithmetic, with no fallback edge between them. | yes | `PASS` |
| `ENV-K-07` | The vault's envelope carries its own integrity check, verified before the platform is reached. | yes | `PASS` |
| `ENV-K-08` | No credential reaches an output stream, and the gate that says so runs over what was actually written. | yes | `PASS` |

### L — Degraded operation

| ID | Requirement | Blocking | Status |
|---|---|---|---|
| `ENV-L-01` | Every component GLOBIN reaches for is declared with a necessity, and the posture is folded from what each factory actually returned. | yes | `PASS` |
| `ENV-L-02` | A declared-required component whose question does not yet arise is recorded honestly rather than made to pass. | yes | `PASS` |
| `ENV-L-03` | The network row is declared rather than probed. | yes | `PASS` |

### M — Band closure

| ID | Requirement | Blocking | Status |
|---|---|---|---|
| `ENV-M-01` | Whether Phases 017-032 were drawn at a granularity that describes the work is answered on the record. | yes | `PASS` |
| `ENV-M-02` | No document defers a question to a phase that has already delivered. | yes | `PASS` |
| `ENV-M-03` | The band's documentation agrees with what the band built. | no | `PASS` |
| `ENV-M-04` | The environment band is certified by a matrix the release gate recomputes, not by assertion. | yes | `PASS` |

---

## Unresolved

One criterion is not `PASS`, and one that is deserves a note.

**`ENV-F-04` — CUDA benefit measured on a device. `BLOCKED`, non-blocking.**
Every CUDA workload in the benchmark contract records `unavailable`, naming
`torch` and Phase 183. That is a measurement rather than a hole: nothing is
stubbed, and the reason is recorded per workload. It depends on a device and a
library outside this repository, which is exactly what `BLOCKED` means, and
ADR-0045 makes it outrank a failure rather than round down to one.

**`ENV-C-04` — the packaging build. `PASS`, non-blocking, and newly so.**
`MEMORY.md` and `QUALITY_GATES.md` both carried a deferral against Phases
017-032 saying no packaging build had been run and that describing one as
verified before then was forbidden. Phase 032 is the last of those phases, so it
ran one. The wheel and the source distribution were built, installed into a
throwaway environment, and exercised: `globin --version` answered its version and
`globin bootstrap check` refused at `python.environment` — the fail-closed refusal
Phase 021 designed, reached from an installed artefact rather than from the source
tree, which is the thing the deferral existed to make somebody demonstrate.

**It is non-blocking, and the reason is a finding rather than a caveat.**
Building is verified, not gated. `hatchling` is the build backend and is **absent
from `pylock.dev.toml`**, so build isolation reaches an index. Every command in
`QUALITY_GATES.md` runs offline, and adding one that does not would make that
sentence false. Making this recurring means locking the build backend, which is a
dependency review under [`../DEPENDENCY_POLICY.md`](../DEPENDENCY_POLICY.md)
rather than a line of tooling.

---

## What was reconciled

A band-closing phase exists to pay down inconsistency, and
[`../engineering/DOCUMENTATION_STANDARD.md`](../engineering/DOCUMENTATION_STANDARD.md)
says these phases exist "for exactly this". What Phase 032 found:

**Twenty-three stale deferral rows across nine documents**, each pointing a
reader at a phase that had already delivered. The check that should have caught
them covered five documents out of twenty-three, because it walks from a literal
`| Question | Phase |` header and nine documents carried the same table under a
different one — `| Question | Where |`, `| Question | Owner |`,
`| Question | Owning phase |`, and in one case `| Not registered | Owner |`.
Every unregistered document had drifted. The headers were normalised rather than
the parser taught a second spelling, because a parser that accepts two will
accept a third.

**A published evidence section that published nothing.** `observed.secrets` in
the bootstrap manifest had been the literal string `[redacted]` since Phase 029:
`redact` matches field names by case-insensitive substring, and `secrets`
contains `secret`. The record it was hiding is a count and a list of reference
*names*, which `SECURITY_BASELINE.md` section 1 calls ordinary data — so nothing
was protected and a reader was simply told nothing. Every accurate rename is
caught by the same mechanism, so the section is now `references`, after the type
it carries, and the manifest schema moved from 2 to 3.

**Three documents contradicting themselves or the tree.** `CLAUDE.md` said six
libraries were absent-safe and then, twelve lines later, said four while listing
three. `MEMORY.md` recorded phases 001-030 complete after 031 had shipped.
`FOUNDATION_ACCEPTANCE.md` named this band by a title that does not exist and
left three handoff rows unmarked after their phases delivered.

---

## Phase 033 handoff

**Phase 033 may begin.** The next band, *Phases 033-048, Binance API Reality Map
and Capability Matrix*, is the first that reaches a venue.

**What Phase 033 inherits.** A host whose contract is recomputed rather than
believed; an environment built without activation and repaired without
recreation; dependencies locked, hash-pinned and installable offline; an
application that refuses to start fail-closed with one exit code per failure
class; a runtime tree with one coordinator per machine; diagnostics, health, a
watchdog and telemetry that are all absent-safe; configuration that explains
which source set each value; and two secret mechanisms disjoint by arithmetic.

**What Phase 033 must not assume.** That any credential exists. That
`required_references()` is non-empty — it is empty by derivation, and Phase 039
fills it. That a permission has ever been *confirmed*: `VerificationState` has no
member for it, deliberately, because no venue has been reached. That the network
is reachable — the degradation contract declares that row rather than probing it,
and Phase 045 owns measuring it.

**What Phase 033 should read first.**
[`../engineering/GRANULARITY_REVIEW.md`](../engineering/GRANULARITY_REVIEW.md),
and specifically its inheritance table: sixteen phases that have not started
already have part of their subject built, and three of them are collided with by
title.

---

## Related documents

| Question | Phase |
|---|---|
| Whether the *foundation* band was certified | 016, delivered — [`FOUNDATION_ACCEPTANCE.md`](FOUNDATION_ACCEPTANCE.md) |
| How a version is chosen and a release cut | 016, delivered — [`RELEASE_POLICY.md`](RELEASE_POLICY.md) |
| Whether the band's phases were drawn at the right granularity | 032, delivered — [`../engineering/GRANULARITY_REVIEW.md`](../engineering/GRANULARITY_REVIEW.md) |
| Which gates recompute these criteria | 004, delivered — [`../engineering/QUALITY_GATES.md`](../engineering/QUALITY_GATES.md) |
| Whether ADR-0021's amendment test should be replaced | 048 |
