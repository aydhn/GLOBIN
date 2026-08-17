# ADR-0075 — Native architecture is measured through one adapter, and a fingerprint excludes what moves

## Status

Accepted — Phase 028.

**Date:** 2026-08-18

## Context

Phase 017 declared the runtime baseline and Phase 021 taught the bootstrap to check a
host against it. Both compare `platform.machine()` — or its equivalents — against
`runtime-contract.toml`'s `architecture = "AMD64"`. That answers what the *process* runs
on and says nothing about the *machine*, because the two can differ: an x64 interpreter
on an ARM64 Windows host runs under emulation, correctly and more slowly, and every
standard-library route reports x64.

Nothing in the tree distinguished the two, and nothing produced a stable identifier for
"this environment" that a reader could compare between runs.

## Decision

Three decisions, each with a refusal inside it.

1. **`IsWow64Process2` is the only source for the native architecture.** Where it is
   absent, the native architecture is `UNKNOWN`.
2. **An unmeasurable required capability degrades rather than blocks.**
3. **The compatibility fingerprint is computed over a separate type that has no field
   for anything volatile**, rather than over a snapshot with volatile keys filtered out.

## Consequences

### The fallback is documented to lie, so it does not answer the question it looks like it answers

`phase_028_sources.md` S-02 quotes Microsoft on `GetNativeSystemInfo`: "If the function
is called from an x86 or x64 application running on a 64-bit system that does not have an
Intel64 or x64 processor (such as ARM64), **it will return information as if the system
is x86**". Its own Remarks then route the question elsewhere: "To determine if a
Win32-based application is running under WOW64 (or if a 64-bit system does not have an
Intel64 or x64 processor), call the `IsWow64Process2` function."

So the obvious fallback is wrong in **exactly the case native detection exists for**, and
wrong in a way no caller could notice. `WindowsArchitectureApi` keeps it for the
*process* question, where the function is equivalent to `GetSystemInfo` and correct, and
records `UNKNOWN` for the native one.

**This changed the phase's plan.** The approved plan said "fall back to
`GetNativeSystemInfo`" without qualification.

### The constant's name says the opposite of what the value means

`IMAGE_FILE_MACHINE_UNKNOWN` is `0`, and S-01 quotes the documentation: "The value will
be IMAGE_FILE_MACHINE_UNKNOWN if the target process is **not** a WOW64 process."

A mapping written against the constant's *name* would read `0` as "unknown architecture"
and report every ordinary native machine as unmeasured. S-03 measured that this
development host returns exactly that value on every run, so the mistake would have been
permanent rather than rare — a host that is fine, reported amber for ever.
`_architecture_from_wow64` reads `0` as "not emulated" and derives the process
architecture from the native machine, and
`test_a_process_machine_of_unknown_means_native_not_unmeasured` is what holds that.

### Degrading rather than blocking is what keeps a supported host startable

`runtime-contract.toml` declares `minimum_release = "10"` with no build component, and
S-01 records that `IsWow64Process2` arrived in Windows 10 version **1709**. A supported
host may therefore be unable to answer the native question at all.

[ADR-0045](0045-a-platform-capability-is-a-recorded-state-never-a-pass.md) already
decided that absence is a state rather than a failure, for a *device*. This applies the
same rule to a *question*: `CapabilityStatus.UNKNOWN` on a required capability reaches
`EnvironmentCompatibility.DEGRADED`, never `BLOCKED`, and `capability_outcome` renders
that as a `WARN` which `exit_code_for` ignores. Only `UNSUPPORTED` on a required
capability blocks.

The same rule is what keeps continuous integration honest rather than permanently red:
the hosted runner is a legitimate machine that cannot answer everything this one can.

### Emulation is a separate check from architecture, and it is optional

An x64 interpreter on an ARM64 host is supported and slower. Folding it into the
architecture check would force a single verdict on two different situations — "this host
is the wrong architecture" and "this host is the right architecture, reached indirectly"
— which have different remedies. They are two checks, and the second is
`OPTIONAL`/`DEGRADED`.

### Every toolchain capability is optional, and there is no way to declare otherwise

`toolchain_checks` has no parameter that could make one required. GLOBIN itself invokes
none of `git`, `py` or `powershell` at run time; they are what *developing and verifying*
GLOBIN needs, which is a different question about a different host. S-10 measured
`pwsh` absent on this machine while `powershell` is present, and nothing here invokes
`pwsh` — so it is not declared, because listing it would report a shortfall against a
requirement that does not exist.

### The fingerprint excludes volatile fields by type, not by filter

`compatibility_fingerprint` accepts a `CompatibilityProjection`, which has exactly two
fields — the checks and the architecture. It has nowhere to put a timestamp, a process
identifier, a duration, a temporary name or an absolute path.

The alternative, hashing a snapshot with a denylist of volatile keys removed, was
rejected for the reason
[`../engineering/SOURCE_OF_TRUTH.md`](../engineering/SOURCE_OF_TRUTH.md) gives about
second copies: a denylist is a list somebody must remember to extend, and the failure
when they do not is a fingerprint that changes every run — useless for exactly the
comparison it exists to serve. A later phase adding a volatile field to
`EnvironmentCapabilitySnapshot` cannot change a fingerprint, because the field has
nowhere to go in the projection.

Three further exclusions are deliberate. **`observed` and `expected` are outside it**,
because they carry human-readable text that can be reworded without the host changing.
**The toolchain is outside it**, because installing Git changes a report without changing
which environment this is. **Registry order is outside it**, because the canonical
rendering sorts by identifier — so a phase inserting a check ahead of another does not
invalidate every recorded fingerprint.

### One adapter per library, enforced on the import graph

`globin.adapters.environment` is the only module that may load `kernel32`, and
`globin.adapters.secrets` the only one that may load `advapi32`.
`tests/architecture/test_credential_discipline.py` enforces both in each direction —
nothing else loads them, and each permitted module still does. It is the shape
`test_probe_discipline.py` gave `psutil` in Phase 024, for the same reason: the absence
is handled in one place so that every layer above is written as though the library were
present.

## Alternatives Considered

**Use `platform.machine()` for the native architecture.** It describes the process, not
the host, and reports x64 under emulation — the same defect as the `GetNativeSystemInfo`
fallback, with no documentation warning about it.

**Fall back to `GetNativeSystemInfo` for the native architecture anyway, and accept the
ARM64 error.** Declined. It would produce a confident wrong answer in the one case the
capability exists to detect, which is worse than no answer under ADR-0045's rule.

**Make an unmeasurable required capability block.** Declined. It would refuse to start a
host that satisfies the declared contract, over a question the host cannot answer —
treating an absent measurement as a failed one.

**Extend `tools/quality/runtime/` instead of building in the package.** Declined because
the package cannot import `tools`, so `globin doctor` and the readiness endpoint could
not reach it. This is a second *reader* of one declaration, which
`globin.adapters.bootstrap` already established as the precedented shape: "One
declaration, two readers, and neither of them a copy of the other."

**Produce operating-system, interpreter and virtual-environment checks here as well.**
Declined, and this is the largest refusal in the phase. Phase 021's `checks()` already
judges all three against the same contract. Two verdicts about one fact is drift, and a
reader would have no way to decide which was authoritative.

## Risks and Trade-offs

**The architecture probe is untested against a real ARM64 host**, because none exists
here. Every emulation case is exercised through a fake `kernel32`. That is the same
limitation `tools/quality/gpu/` accepts about a machine with no NVIDIA device, and it is
recorded rather than hidden: what is proven is that the *classification* is right given
what the API reports, not that the API reports what is expected on hardware nobody has
run this on.

**The `ctypes` tripwire is a proxy, not a proof.** It matches literal library names, so
`ctypes.WinDLL(computed_name)` defeats it — asserted as a failing row in the guard's own
table rather than left to prose.

**The fingerprint is 32 hexadecimal characters, half a SHA-256.** Short enough to read
and long enough that two genuinely different environments will not collide in practice.
It is not a security boundary and nothing authenticates with it.

## References

- [ADR-0045](0045-a-platform-capability-is-a-recorded-state-never-a-pass.md) — absence is a recorded state
- [ADR-0050](0050-the-runtime-is-a-declared-contract-and-venv-is-its-only-environment.md) — the contract this is judged against
- [ADR-0073](0073-phase-028-widens-to-deliver-the-environment-capability-inventory.md) — the amendment this arrived under
- [`../engineering/ENVIRONMENT_CAPABILITY.md`](../engineering/ENVIRONMENT_CAPABILITY.md) — the model, and how to read a verdict
- [`../research/phase_028_sources.md`](../research/phase_028_sources.md) — S-01, S-02, S-03, S-09 and S-10

## Supersedes

Nothing.

## Superseded By

Nothing.
