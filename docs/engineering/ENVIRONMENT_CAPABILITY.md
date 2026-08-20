# Environment Capability

What GLOBIN needs of the machine it runs on, how a shortfall is classified, and
how to read the verdict.

This is about **fitness**, not identity.
[`RUNTIME_BASELINE.md`](RUNTIME_BASELINE.md) declares which host and which
interpreter are supported, and [`BOOTSTRAP.md`](BOOTSTRAP.md) describes the
checks that hold a machine to it. Everything here sits alongside those and asks a
question they cannot: given a host that satisfies the declared contract, is it
*capable* of what GLOBIN needs?

Reasoning:
[ADR-0075](../adr/0075-native-architecture-is-measured-through-one-adapter-and-a-fingerprint-excludes-what-moves.md).
Every platform claim below is measured, and
[`../research/phase_028_sources.md`](../research/phase_028_sources.md) records
each with what it answered.

---

## The command

```bash
.venv\Scripts\globin.exe diagnostics environment
```

```bash
.venv\Scripts\globin.exe diagnostics environment --json
```

It reads only. It starts nothing, binds nothing, writes nothing, and reaches no
network. The same measurement reaches `globin doctor` and `globin bootstrap
check` as one registered check, `environment.capability`.

---

## What is measured

| Capability | Severity | What it asks |
|---|:--:|---|
| `environment.architecture.native` | **Required** | Is the host's own processor architecture the one `runtime-contract.toml` declares? |
| `environment.architecture.emulation` | Optional | Is this process running natively on that architecture, or through emulation? |
| `environment.toolchain.git` | Optional | Is Git resolvable? Used by the release and supply gates. |
| `environment.toolchain.py` | Optional | Is the Python launcher resolvable? Used by `scripts/bootstrap.ps1`. |
| `environment.toolchain.powershell` | Optional | Is Windows PowerShell resolvable? Runs `scripts/verify.ps1`. |

**Every toolchain capability is optional and there is no way to declare one
required.** GLOBIN itself invokes none of them at run time; they are what
*developing and verifying* GLOBIN needs, which is a different question about a
different host. A required toolchain would make a correctly provisioned
production machine refuse to start.

`pwsh` is deliberately absent from that list. PowerShell 7 is not installed on
the development host and nothing in this repository invokes it, so listing it
would report a shortfall against a requirement that does not exist.

### What is deliberately *not* measured here

The operating system, the interpreter, and the virtual environment. All three are
already judged against the same `runtime-contract.toml` by
`globin.domain.bootstrap.checks()`, and a second verdict about one fact is the
drift [`SOURCE_OF_TRUTH.md`](SOURCE_OF_TRUTH.md) exists to prevent — worse than
ordinary duplication, because the two could disagree and a reader would have no
way to decide which was authoritative.

---

## Native architecture is not process architecture

An x64 interpreter on an ARM64 Windows host runs under emulation: correctly,
more slowly, and invisibly to `platform.machine()`, which reports x64. The two
are separate questions and GLOBIN answers both.

**Only `IsWow64Process2` can answer the native one honestly.** Microsoft
documents `GetNativeSystemInfo` as reporting an ARM64 host "as if the system is
x86", and its own Remarks route the question to `IsWow64Process2`. So:

- Where `IsWow64Process2` exists, it is authoritative for both questions.
- Where it does not — it arrived in Windows 10 version **1709**, and the runtime
  contract declares a floor of "10" with no build component — the native
  architecture is recorded as `UNKNOWN` and the fallback answers the *process*
  question only.

A confident wrong answer would be worse than no answer in exactly the case the
capability exists to detect.

**One trap worth knowing if you read the code.**
`IMAGE_FILE_MACHINE_UNKNOWN` is `0`, and Windows reports it when the process is
**not** emulated. It does not mean "unknown architecture". A native AMD64 host —
including this one, on every run — returns it every time.

---

## Statuses, and what each one costs

| Status | Meaning |
|---|---|
| `supported` | Measured, and it is what GLOBIN needs. |
| `unsupported` | Measured, and it is not. |
| `degraded` | Measured, usable, and worse than intended. |
| `unknown` | **Not measured.** The probe was unavailable or the only available answer is documented to be wrong. Never a synonym for "no". |
| `not_applicable` | The question does not arise on this host. |

The verdict folds those into three:

| Verdict | Reached when | Exit code |
|---|---|:--:|
| `READY` | Everything supported. | `0` |
| `DEGRADED` | Anything degraded, unmeasured, or an absent optional. | `0` |
| `BLOCKED` | A **required** capability measured `unsupported`. | `24` |

**An unmeasurable required capability degrades; it does not block.** This is the
single most consequential rule here, and it follows
[ADR-0045](../adr/0045-a-platform-capability-is-a-recorded-state-never-a-pass.md):
a capability that could not be measured has not been shown to be absent.
Refusing to start a host over a question it cannot answer would treat an absent
measurement as a failed one — and would make continuous integration, which runs
on a machine that legitimately cannot answer everything this one can, red for
ever.

**Exit code `24` is deliberately not `10`.** `HOST_UNSUPPORTED` means the machine
failed the declared contract — wrong operating system, wrong release.
`ENVIRONMENT_INCOMPATIBLE` means it *satisfies* that contract and lacks a
capability the contract does not describe. A launcher should treat those
differently: one is a machine GLOBIN was never meant to run on, the other is one
that was provisioned wrongly.

---

## The compatibility fingerprint

A 32-character hexadecimal digest identifying **this environment's compatibility
state**, so that two runs can be compared without reading five checks.

```text
environment  ready  (0147b5ac138b4b967134701c8b5ba56a)
```

### What it covers

Every check's identifier, category, severity, status and reason; and the process
architecture, native architecture and emulation state.

### What it excludes, and why

| Excluded | Why |
|---|---|
| Timestamps, process ids, durations, temporary names | Volatile. A fingerprint that moved every run would be useless for the one comparison it exists to serve. |
| Absolute paths | Never representable — no type in the chain has a field for one. |
| `observed` and `expected` text | Human-readable, and reworded for editorial reasons without the host changing. |
| The toolchain | Every toolchain capability is optional; installing Git changes a report without changing which environment this is. |
| Registry order | The canonical rendering sorts by identifier, so a phase inserting a check ahead of another does not invalidate every recorded fingerprint. |

**The exclusion is structural, not a filter.**
`compatibility_fingerprint` accepts a `CompatibilityProjection`, a type with
exactly two fields and nowhere to put anything volatile. A denylist of volatile
keys would be a list somebody must remember to extend, and the failure when they
do not is a fingerprint that changes on every run.

It is **not a security boundary** and nothing authenticates with it.

### Where it is published

In the bootstrap manifest, under `observed.environment`, alongside every other
fact a start-up measured:

```bash
.venv\Scripts\globin.exe bootstrap evidence
```

There is deliberately **no separate `.globin/environment/` manifest**. The
snapshot is a fact about this start-up, and the bootstrap manifest is where this
repository already records those; a second artefact would need its own schema,
digest and reader for a section that fits in the one that exists.

---

## Privacy

No path leaves the capability layer, and that is a property of the types rather
than of what a caller chooses to print. The toolchain probe returns a
**boolean**; the resolved location is discarded where it was found. On this host
every absolute path outside the repository contains the account holder's full
name, which is why `tools/quality/runtime/plan.py` already recorded this rule
about its own manifest.

Nothing here publishes `PATH`, an environment variable's value, a username, a
hostname, or a home directory.

---

## Remediation

| Reason code | What to do |
|---|---|
| `architecture_mismatch` | The host's processor architecture is not the declared one. Either run GLOBIN on a machine matching `runtime-contract.toml`, or change the declaration deliberately and re-verify. |
| `running_emulated` | This process is emulated on a different native architecture. It works. Install an interpreter built for the host's own architecture to remove the cost. |
| `probe_unavailable` | The Windows API that answers this question is absent, which means a release older than Windows 10 version 1709. The host is not refused; the question is simply unanswered. |
| `executable_absent` | An optional developer tool is not on `PATH`. Nothing blocks. Install it if you intend to run the gate that uses it. |

---

## What this does not cover

| Question | Phase |
|---|---|
| Which host and interpreter are supported | [`RUNTIME_BASELINE.md`](RUNTIME_BASELINE.md) |
| Whether this machine still matches an accepted baseline | [`ENVIRONMENT_DRIFT.md`](ENVIRONMENT_DRIFT.md) |
| Whether a GPU is present, and whether using it pays | [`GPU_CAPABILITY.md`](GPU_CAPABILITY.md), [`GPU_BENEFIT.md`](GPU_BENEFIT.md) |
| The full set of preflight checks a long-running process needs | 030, delivered — [`PREFLIGHT_SUITE.md`](PREFLIGHT_SUITE.md) |
| Behaviour when the network or an optional native component is unavailable | 031, delivered — [`DEGRADED_OPERATION.md`](DEGRADED_OPERATION.md) |
| Which products and environments the venue offers | Phase 036 |

Only the last of those is still unbuilt, and nothing here anticipates it. The two above it were delivered by Phases 030 and 031 and the sentence was not moved with them.

---

## Related

- [ADR-0075](../adr/0075-native-architecture-is-measured-through-one-adapter-and-a-fingerprint-excludes-what-moves.md) — the decisions, and the refusals inside them
- [ADR-0045](../adr/0045-a-platform-capability-is-a-recorded-state-never-a-pass.md) — why an unmeasurable capability degrades
- [ADR-0073](../adr/0073-phase-028-widens-to-deliver-the-environment-capability-inventory.md) — the amendment this arrived under
- [`BOOTSTRAP.md`](BOOTSTRAP.md) — the check registry this joins, and the exit-code contract
- [`../research/phase_028_sources.md`](../research/phase_028_sources.md) — every platform claim, with its source
