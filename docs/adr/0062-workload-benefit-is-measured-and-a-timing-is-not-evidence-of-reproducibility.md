# ADR-0062 — Workload benefit is measured against a declared contract, and a timing is not evidence of reproducibility

## Status

Accepted — Phase 024.

**Date:** 2026-08-16

## Context

`ROADMAP.md` row 024 asks for a harness that "proves which workloads actually
benefit from GPU execution on this host".
[ADR-0060](0060-gpu-capability-is-detected-and-the-runtime-explains-itself.md)
sharpened that by refusing to answer it early: Phase 023 detects and records, and
"nothing here times anything".

Two facts about this repository shape what such a harness can honestly be.

**No CUDA-capable library is adopted.**
[`../engineering/wheel-survey.toml`](../engineering/wheel-survey.toml) files no
library under phase 24 and `torch` under phase 183, and
[`../DEPENDENCY_POLICY.md`](../DEPENDENCY_POLICY.md) makes adopting one a written
decision. So on every host GLOBIN currently has, no CUDA workload can run.

**Every other gate in this repository produces byte-identical evidence, and this
one cannot.** Ten gates check that two renderings of the same run agree, and treat
a disagreement as the manifest identifying nothing. A benchmark's central output is
a nanosecond count, which differs on every run because a general-purpose machine is
doing other things.

## Decision

**A benefit harness is built, the contract declares the method, and every verdict
is recomputed from recorded measurements.**

`python -m tools.quality benchmark` reads
[`../engineering/benchmark-contract.toml`](../engineering/benchmark-contract.toml),
runs what it can, and writes `.globin/benchmark/benchmark-manifest.json`.

### The determinism claim is narrowed, not dropped

The manifest is split so a reader knows which half to compare. `run.observed` holds
nanoseconds, which move. `findings` holds verdicts, which are a pure function of
the contract and those nanoseconds.

The double-render check every other gate applies to its whole document is applied
here to the **findings half only**. That is the honest form of the check rather
than a weakening: comparing the timings would make the gate fail for exactly the
property it exists to measure, while comparing the derivation still catches the
defect that matters — a verdict that is not a function of its inputs. Three
documents say so, so nobody has to discover it from a failing comparison.

### An unadopted backend is a state

The four states are ADR-0045's, and the middle two are deliberately distinct.
`unavailable` means the library is not adopted here, and names the phase that would
change that. `absent` means no device of the required kind exists, and installing
more would not help. Telling an operator to install something that would not help
them is a different kind of wrong from telling them nothing.

`error` always fails the gate, because not knowing *why* something did not run
differs from knowing why.

**Nothing is stubbed or simulated.** A harness that invented a figure for an
unavailable backend would be the exact failure ADR-0045 exists to prevent, dressed
as a measurement.

### The method is declared once, and it is the minimum of several runs

Warmup, repeats, reduction and clock live in the contract rather than in the
runner, so two workloads' figures are comparable with each other. The reduction is
`minimum` because every source of noise on this machine *adds* time — another
process, a page fault, a frequency change — so the minimum is the closest available
estimate of the workload's own cost, and a mean on a laptop largely measures what
else the laptop was doing.

### A CUDA measurement synchronises, and a threshold is not 1.0

Device work is queued asynchronously, so a timed block returning as soon as the
call was *submitted* records submission cost and reports a speedup of several
hundred. This is the single most common way a GPU benchmark lies, and it lies in
the flattering direction. `probes.py` synchronises before returning.

The declared threshold is 2.0 for every CUDA workload rather than 1.0, because
getting data to the device and back costs real time: a workload 1.1× faster on the
GPU is slower in any pipeline that has to make the round trip.

### Four GPU capabilities change owner

[`../engineering/gpu-contract.toml`](../engineering/gpu-contract.toml) filed
`gpu.present`, `gpu.driver_version`, `gpu.compute_capability` and
`cuda.runtime_present` under `phase = 24`. `phase_problems` fails any capability
naming a delivered phase, because that is a gap nobody will ever close, so shipping
Phase 024 with `DELIVERED_PHASE` raised to 24 would have failed on all four.
ADR-0060 recorded exactly this as its fifth risk.

They move to **phase 31**, *Offline and Degraded Installation Handling*, and the
move is a correction rather than a deferral. Phase 024 *consumes* those
capabilities — the harness reads them to decide whether a CUDA workload is
measurable — and does not answer for their absence. The phase that still owes an
answer to "what does GLOBIN do when there is no device" is 031, whose whole subject
that is, and each capability's existing `absence_means` already reads as an input
to it.

### The floor is applied asymmetrically

`phase_problems` in this package refuses a *delivered* phase only for a non-`cpu`
workload. A `cpu` workload names the phase that adopted the library it already uses
— `numpy`, Phase 021 — which is necessarily delivered. A non-`cpu` workload that is
unmeasurable names the phase that *would* make it measurable, and there a delivered
phase is the gap ADR-0052 refuses.

## Consequences

The gate is registered in the one command table, sits between `gpu` and the
mutating commands, and is in neither `fast` nor `full` — it reports on the
**machine** rather than on the tree, so its verdict can change without a commit and
a commit cannot change it. That is ADR-0032 condition 5, and the same argument
`gpu` makes about itself.

`docs/engineering/GPU_BENEFIT.md` becomes a document that must be kept true.

A fourth mypy override is added, for `torch`, and it is the only one for a library
this repository has not adopted and does not install. The override carries its own
expiry: when Phase 183 adopts torch — which ships `py.typed` — the line starts
hiding real errors and is removed.

Whoever reaches Phase 183 inherits a harness with somewhere to put an answer, and
`benchmark-contract.toml` is where the threshold that decides "worth it" is
already written down.

## Alternatives Considered

**Adopt a CUDA library now so the harness has something to measure.** Rejected:
`torch` is a very large dependency owned by Phase 183, and adopting it here to make
a gate produce numbers would be the tail wagging the dog — precisely the
"adoption wearing a survey's clothes" ADR-0052 names.

**Record only CPU baselines and leave CUDA out of the contract entirely.** Simpler,
and it would have made the manifest look complete. Rejected because the question
the roadmap asks is about GPU benefit, and a contract that declined to name the
workloads it could not measure would answer a different, easier question and look
like it had answered this one.

**Compare the whole manifest for determinism and accept that it fails.** Rejected
because a gate that is known to fail is a gate people stop reading.

**Drop the determinism check entirely for this gate.** Rejected because the
derivation genuinely should be a pure function, and that is worth checking; the
narrowing keeps the property that can be true.

**Leave the four capabilities at phase 24 and hold `DELIVERED_PHASE` at 23.**
Rejected because the floor would then permanently understate what has shipped, and
the next phase to raise it would hit the same wall with no record of why.

## Risks and Trade-offs

**The characteristic failure mode is a reader comparing two manifests and reporting
drift.** The observable signal is a bug report about `benchmark-manifest.json`
changing between runs. The mitigation is that three documents and the manifest's own
module docstring say which half moves.

**The second is that a threshold is treated as a measurement.** 2.0 is a judgement
about transfer cost at the declared array sizes, not something anybody measured on
this host. The signal that it has been over-read is a phase citing it as evidence
rather than as policy.

**The third is that the CPU baselines drift into being a performance regression
suite.** They exist to give a CUDA figure something to divide by. If a later phase
starts failing the gate because a baseline got slower, it has acquired a second
purpose that nothing here was designed for.

Confidence is high on the contract recomputation and the state model, which reuse
patterns four gates already prove. It is moderate on the workload set, which is
three shapes chosen because they are the shapes a numerical stack does, and which
Phase 183 may well replace with the operations GLOBIN actually runs.

## References

- [ADR-0032](0032-verification-tooling-may-be-added-outside-phase-scope.md) — the six conditions this gate is placed under
- [ADR-0045](0045-a-platform-capability-is-a-recorded-state-never-a-pass.md) — absence is a recorded state, never a pass
- [ADR-0052](0052-wheel-availability-is-a-recorded-survey-whose-verdict-is-recomputed.md) — a gap must name a phase that can still close it
- [ADR-0058](0058-the-scientific-stack-is-verified-by-measurement-and-stays-in-the-approximate-regime.md) — the numpy this harness measures with
- [ADR-0060](0060-gpu-capability-is-detected-and-the-runtime-explains-itself.md) — the detection this consumes, and the fifth risk this resolves
- [ADR-0061](0061-phase-024-widens-to-deliver-runtime-health-and-support-bundles.md) — the amendment this half sits inside
- [`../engineering/GPU_BENEFIT.md`](../engineering/GPU_BENEFIT.md) — the prose form of this record

## Supersedes

None.

## Superseded By

None.
