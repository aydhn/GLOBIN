# GPU Capability

What this machine's graphics hardware actually is, measured rather than assumed —
and why every answer is a recorded state instead of a pass.

This document owns GPU detection policy. The contract it describes lives in
[`gpu-contract.toml`](gpu-contract.toml), the gate that recomputes it is
`tools/quality/gpu/`, and `tests/contract/test_gpu_contract.py` compares the two
so that a rule changed in one place cannot stay unchanged here.

---

## What Phase 023 was asked for

`ROADMAP.md` gives Phase 023 one job: *detect GPU presence, driver version,
compute capability and CUDA availability without assuming any of them*. The band
says the same thing again — "honest verification of GPU capability rather than
assumption".

Read carelessly that sounds like a small job: run a tool, read four numbers. The
reason it is not is in [the traps](#the-four-traps-this-phase-actually-found)
below, every one of which was measured on the target host rather than remembered.

---

## Absence is a state, not a failure

A machine with no NVIDIA device is a fact about the machine. A gate that went red
for it would be reporting the hardware rather than the repository, and it would be
red forever on the only host that must stay green: continuous integration runs on
`windows-latest`, which has no GPU at all.

So this follows [ADR-0045](../adr/0045-a-platform-capability-is-a-recorded-state-never-a-pass.md),
which settled the same argument for platform controls. Four states, and no fifth:

| State | Meaning |
|---|---|
| `PRESENT` | Asked, and found |
| `ABSENT` | Asked, and this host does not have it. **Not a failure** |
| `UNMEASURABLE` | Not asked, because something it depends on was absent |
| `ERROR` | The probe itself failed |

`ABSENT` and `UNMEASURABLE` are separate because *the device says no* and *there
was no device to ask* are different claims, and a later phase reading the manifest
needs to tell them apart. On a host with no driver, `gpu.present` is `ABSENT` and
everything downstream of it is `UNMEASURABLE`.

`ERROR` always fails the gate, whatever the capability's policy. An optional
capability that is missing is information; an optional capability nobody could
measure is an unanswered question wearing information's clothes.

### What does fail

- A contract that cannot be parsed, or that contradicts itself by both permitting
  and forbidding the same field.
- A capability whose gap is owned by nobody, or owned by a phase that has already
  shipped — the rule [ADR-0052](../adr/0052-wheel-availability-is-a-recorded-survey-whose-verdict-is-recomputed.md)
  established for the wheel survey, applied to hardware.
- A probe in `ERROR`.
- A manifest that is not reproducible, or that carries something unpublishable.

---

## The contract declares an interface, not a baseline

[`gpu-contract.toml`](gpu-contract.toml) records **no driver version, no compute
capability and no device name**. That is the difference between it and the
accepted baseline in [`ENVIRONMENT_DRIFT.md`](ENVIRONMENT_DRIFT.md).

A driver updates on its own schedule. A file pinning `610.88` would go red on a
Tuesday for a reason nobody in this programme decided, and the bump would then be
applied without being read — which is how a check stops meaning anything. What is
declared instead is the *interface* and the *policy*: which documented fields may
be asked, which must never be, and who answers for an absence. The observed values
live in `.globin/gpu/gpu-manifest.json`, which is regenerated and never committed.

---

## The four traps this phase actually found

Each of these was measured on the target host on 2026-08-16 and is recorded with
its exact output in [`../research/phase_023_sources.md`](../research/phase_023_sources.md).
They are the reason "without assuming any of them" is a real instruction.

1. **`cuda_version` is not a queryable field.** `nvidia-smi --query-gpu=cuda_version`
   answers `Field "cuda_version" is not a valid field to query.` and exits
   non-zero. A detector that added it to the query would break the *whole* query,
   not just that column.

2. **`DRIVER version` is self-declared deprecated.** `nvidia-smi --version`
   answers it with `Deprecated, see "KMD version" instead`. A reader taking the
   first matching label would publish that sentence where a version belongs, and
   nothing downstream could tell it from a measurement.

3. **`CUDA version` is deprecated in the same way**, pointing at
   `CUDA UMD version`.

4. **The banner format has changed.** The header line reads
   `CUDA UMD Version: 13.3`, not the older `CUDA Version: 13.3`. Anything
   screen-scraping the banner for the older spelling silently finds nothing.

The response is the `[[forbidden_field]]` table, which the gate checks against the
`[interface]` table in the same file: a field listed in both is a rule with an
exception written directly underneath it, and that fails. Values are additionally
shape-checked — digits and dots for a version, `major.minor` for a compute
capability — so a prose answer is refused rather than recorded.

---

## A runtime is not a toolkit

The driver-side CUDA runtime and an installed CUDA compiler are asked separately,
and **neither is derived from the other**. A host can have either without the
other, and the target host has the first without the second: `CUDA UMD version`
reports `13.3` while `nvcc` is not on the path and `CUDA_PATH` is unset.

The distinction is the difference between *a prebuilt CUDA wheel would run here*
and *CUDA source could be built here*. Collapsing them into one boolean would
destroy exactly the fact Phase 024 needs when it asks which workloads benefit.

It also matters for a decision already recorded in [`../../MEMORY.md`](../../MEMORY.md):
LightGBM's CUDA backend is not supported on Windows. A blanket "CUDA: yes" would
invite precisely the wrong conclusion from it.

---

## What this does not decide

- **Whether any workload should use a GPU.** Phase 024 owns that, and nothing here
  times anything. Recording that a device exists is not recommending it, in the
  same way that Phase 018 surveying a wheel was not adopting it.
- **Which libraries GLOBIN adopts.** That is [`../DEPENDENCY_POLICY.md`](../DEPENDENCY_POLICY.md),
  one written review at a time.
- **Anything about the CUDA toolkit's installation.** Phase 025 owns native
  provisioning, and the contract names it as the owner of that gap.

---

## Running it

```bash
python -m tools.quality gpu
```

It reaches no network. Unlike `wheels` and `supply` it has no networked
subcommand at all, because what this host has is entirely answerable from this
host.

It is in neither `fast` nor `full`, and here the reason is sharper than the
artefact it writes: this gate reports on the **machine** rather than on the tree,
so its verdict can change without a commit and a commit cannot change it. A gate
in `full` should fail for something the commit did. That is
[ADR-0032](../adr/0032-verification-tooling-may-be-added-outside-phase-scope.md)
condition 5.

---

## Related documents

- [`QUALITY_GATES.md`](QUALITY_GATES.md) — which checks are mandatory, and why this one is not
- [`RUNTIME_BASELINE.md`](RUNTIME_BASELINE.md) — the host and interpreter this contract's target is checked against
- [`WHEEL_AVAILABILITY.md`](WHEEL_AVAILABILITY.md) — the survey whose owned-gap rule this reuses
- [`../SOURCE_POLICY.md`](../SOURCE_POLICY.md) — why only `nvidia-smi`'s own documented vocabulary is read
- [`../research/phase_023_sources.md`](../research/phase_023_sources.md) — every measurement behind the traps above
