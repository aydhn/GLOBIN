# GPU Benefit

Which workloads actually benefit from GPU execution on this host, measured rather
than assumed.

[`GPU_CAPABILITY.md`](GPU_CAPABILITY.md) answers *is there a device*. This answers
the question that one deliberately refused: for work GLOBIN actually schedules,
does moving it to the device pay? Recording that a device exists is not a
recommendation to use it, in the same way that surveying a wheel was not adopting
the library.

---

## What is declared, and what is measured

[`benchmark-contract.toml`](benchmark-contract.toml) declares three things and the
gate recomputes everything else from them.

**The method**, once, for every workload — how many iterations are discarded as
warmup, how many are timed, which of them becomes the recorded figure, and which
clock. One method for all of them, so two workloads' numbers are comparable with
each other and not only with themselves.

**The workloads**, each with an identifier, the backend it runs on, the library
that backend needs, the phase that owns adopting that library, the problem size,
and the speedup at which the contract says the backend is worth using.

**The target**, copied from [`runtime-contract.toml`](runtime-contract.toml) as a
tripwire. If the two disagree the gate refuses rather than measuring the wrong
machine.

```bash
python -m tools.quality benchmark
```

---

## A timing is not reproducible, and a verdict is

This is the one manifest in the repository that is not byte-stable between runs,
and the document says so rather than hoping nobody notices.

`.globin/benchmark/benchmark-manifest.json` is split for that reason.
`run.observed` holds nanoseconds, which differ on every run because a
general-purpose machine is doing other things. `findings` holds verdicts, which
are a pure function of the contract and those nanoseconds, and which the gate
recomputes on every read.

The determinism check every other gate applies to its whole document is therefore
applied here to the **findings half only**. That is the honest form of the check
rather than a weakening of it: comparing the timings would make the gate fail for
exactly the property it exists to measure, while comparing the derivation catches
the defect that actually matters — a verdict that is not a function of its inputs.

**The reduction is the minimum, not the mean.** Every source of noise on this
machine *adds* time: another process, a page fault, a frequency change. The
minimum of several runs is the closest available estimate of the workload's own
cost, and a mean on a laptop largely measures what else the laptop was doing.

---

## Almost everything is `unavailable`, and that is the answer

Today every CUDA workload records `unavailable`, naming `torch` and Phase 183.
That is a measurement, not a hole.

[`wheel-survey.toml`](wheel-survey.toml) files no library under phase 24, and
[`DEPENDENCY_POLICY.md`](../DEPENDENCY_POLICY.md) makes adopting one a written
decision. So this phase builds the harness and records what it could not measure,
which is what lets Phase 183 put a number where an assumption would otherwise go.

The four states are the ones ADR-0045 established, and the distinction between the
middle two is operational rather than pedantic:

| State | Meaning | What an operator would do |
|---|---|---|
| `measured` | The workload ran and produced a figure | Read the speedup |
| `unavailable` | The backend's library is not adopted here | Nothing; a later phase adopts it |
| `absent` | No device of the required kind is present | Nothing; installing more would not help |
| `error` | It was attempted and failed | Investigate — this always fails the gate |

Collapsing `unavailable` and `absent` would tell somebody to install a library
that would not help them, which is a different kind of wrong from telling them
nothing.

---

## The two traps this harness does not fall into

**A CUDA measurement that does not synchronise is a fiction.** Device work is
queued asynchronously, so a timed block returning as soon as the call was
*submitted* records the submission cost and reports a speedup of several hundred.
`tools/quality/benchmark/probes.py` synchronises before returning, and this is the
single most common way a GPU benchmark lies — in the flattering direction.

**A threshold of 1.0 would recommend moves that lose.** Getting data to the device
and back costs real time, so a workload 1.1× faster on the GPU is slower in any
pipeline that has to make the round trip. The contract declares 2.0 for every CUDA
workload, which is the point at which the move pays for the transfer at these
array sizes.

---

## What this does not decide

- **Whether GLOBIN adopts a GPU library.** That is
  [`DEPENDENCY_POLICY.md`](../DEPENDENCY_POLICY.md), one written review at a time,
  and Phase 183 for `torch` specifically.
- **Whether a device exists.** [`GPU_CAPABILITY.md`](GPU_CAPABILITY.md) owns that,
  and this consumes its answer rather than repeating the question.
- **What happens when the GPU is absent at run time.** Phase 031 owns degraded
  operation, which is why this phase moved four capabilities in
  [`gpu-contract.toml`](gpu-contract.toml) into its ownership.
- **Anything about the CUDA toolkit.** Phase 025 owns native provisioning.
