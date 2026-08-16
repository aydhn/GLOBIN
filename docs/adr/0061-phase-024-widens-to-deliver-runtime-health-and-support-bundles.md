# ADR-0061 — Phase 024 widens to deliver runtime health and support bundles, and this is the eighth amendment

## Status

Accepted — Phase 024.

**Date:** 2026-08-16

## Context

`ROADMAP.md` gives Phase 024 one job: *GPU Runtime Verification Harness* — "build a
harness that proves which workloads actually benefit from GPU execution on this
host". That ownership is not stated once. It is in the phase row, in the band's own
description ("including honest verification of GPU capability rather than
assumption"), and in seven further places:
[`../../CLAUDE.md`](../../CLAUDE.md), [`../../CHANGELOG.md`](../../CHANGELOG.md),
[`../ARCHITECTURE_PRINCIPLES.md`](../ARCHITECTURE_PRINCIPLES.md),
[`../engineering/gpu-contract.toml`](../engineering/gpu-contract.toml),
[`../engineering/GPU_CAPABILITY.md`](../engineering/GPU_CAPABILITY.md),
[`../research/phase_023_sources.md`](../research/phase_023_sources.md) and
`tools/quality/gpu/__init__.py`.

The most recent of those is the sharpest.
[ADR-0060](0060-gpu-capability-is-detected-and-the-runtime-explains-itself.md), the
record accepted in the immediately preceding commit, lists under *What the
amendment refuses to build*: "**No benchmark (024).** The GPU half detects and
records. Which workloads benefit is the next phase's question, and nothing here
times anything."

The phase brief handed to this phase asked for something else: a typed runtime
health snapshot, process and host resource diagnostics, memory and thread
introspection, redacted support bundles and deterministic support evidence. Every
one of those subjects is owned by a planned phase **by name** — 030 (bootstrap
health check suite), 260 (resource governor), 276 (status and reporting commands),
280 (operational metrics collection), 282 (log rotation and retention) and 301
(resource consumption profiling).

**The brief's numbering does not match this repository, and did not the last time
either.** It attributed typed configuration to "Phase 19" (actually 007), a secret
store to "Phase 20" (actually 015 for the rules and **028**, unstarted, for the
store), the runtime filesystem to "Phase 22" and logging to "Phase 23" — the last
two being the *amendment halves* of those phases rather than their titles. ADR-0060
recorded the same mismatch about the Phase 023 brief.

The conflict was surfaced to the owner as a choice between four courses — deliver
the roadmap's Phase 024 and record the brief as a proposal; deliver both; deliver
the brief alone and retitle the phase; or deliver the roadmap's harness plus only
the seam no phase owns — and the owner chose to deliver both.

There is nonetheless a real gap, and it should be stated rather than implied. Phase
021 built a bootstrap, Phase 022 gave the process somewhere to keep state, Phase
023 gave it a voice. None of them gave it a way to answer *how am I doing now*:
`doctor` reports on start-up preconditions, not on a running process. And an
operator who hits a fault has no supported way to hand over evidence — they would
be hand-picking files out of a runtime tree, which is how a credential leaves a
machine. That explains why the work has pressure behind it. It does not make the
amendment covered.

## Decision

**Phase 024 delivers both halves**, and this is the **eighth roadmap scope
amendment**.

[ADR-0021](0021-phase-005-widens-to-include-the-test-foundation.md) set a four-part
test for whether an amendment is covered by precedent.
[ADR-0057](0057-phase-022-widens-to-deliver-the-runtime-filesystem-and-lifecycle.md)
removed the option of citing it, and ADR-0060 removed the option of citing *the
series*. The test is therefore restated in full and scored honestly:

| ADR-0021's test | This amendment |
|---|---|
| Nothing displaced | **Fails.** Parts of 030, 260, 276, 280, 282 and 301 arrive here. |
| Nothing deferred | **Holds.** Phase 024's declared GPU scope is delivered in full, and no other phase's title changes. |
| No phase owns the work | **Fails.** Six planned phases own parts of it by name. |
| The two halves need each other | **Fails.** A GPU benefit harness and a health surface are wholly independent. Either could ship alone, and no gate refused until both existed. |

**One of four**, the same score as the sixth and seventh. It is taken on the
owner's explicit decision, made with the conflict and the four alternatives in
front of them.

What distinguishes this one from its two predecessors is worth stating, because it
is the only thing that can be said in its favour and it is not much. The seventh
amendment overlapped Phase 006, which had already **shipped**, and ADR-0060 called
that "duplication of delivered work". This one displaces work only forwards, into
phases that have not started. That is a return to the shape of the fourth, fifth
and sixth rather than an improvement on any of them.

### What the amendment refuses to build

The second half is bounded by what it declines, and the boundary is why the owning
phases still have work.

- **No metrics collection (280) and no audit trail (281).** A snapshot is a
  reading taken when somebody asks. Nothing counts anything, nothing accumulates,
  and no series exists.
- **No operator command surface (276).** There is a local CLI subcommand. There is
  no channel, no authorisation model and no remote anything.
- **No resource governor (260).** Resource figures are reported. Nothing schedules
  against them, and no workload is refused because of one.
- **No profiling suite (301).** `tracemalloc` is exposed as an opt-in reading with
  a bounded top-N. It is not a profiler, it runs nothing in the background, and it
  refuses to stop a tracer it did not start.
- **No retention policy (282).** A bundle bounds what it *includes*. What an
  operator must keep, and for how long, is not decided.
- **No preflight suite (030).** `bootstrap check` is unchanged. A health snapshot
  does not gate anything and cannot refuse a start-up.
- **No configuration file layout (026) or environment resolution (027).** Thirteen
  typed settings arrive through the route
  [`../CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md) documents. **No new
  `os.getenv` call is added anywhere**, holding the line ADR-0057 drew and ADR-0060
  held.
- **No secret store (028).** Nothing here holds, reads or writes a credential, and
  the name `SecretRef` remains forbidden until that phase.
- **No network of any kind**, in either half.

### The one thing outside both halves that was fixed anyway

Adopting `psutil` required regenerating `pylock.toml`, and it turned out that
**nothing could**. `tools/quality/lock`'s `relock` and `upgrade` were written in
Phase 020, when `project.dependencies` was empty and a contract test kept it that
way, so both were hard-wired to the development lock; Phase 021 created the runtime
lock and nothing in the tooling learned about it. With hand-editing a lock
forbidden by
[`../engineering/DEPENDENCY_LOCKING.md`](../engineering/DEPENDENCY_LOCKING.md),
there was no supported route at all.

Worse, the gate could not see the result. `coverage_problems` read `DEVELOPMENT` as
a literal, so every `runtime_*` finding asked only whether `pylock.toml` was sound
*in itself* — hashes, HTTPS, PEP 425 tags, no source distributions — and none asked
whether it held what had been declared. Declaring `psutil` in `pyproject.toml`
**and** in the declaration's `[runtime] roots` while leaving the lock untouched
produced a clean `passed`.

That is a gate reporting success for something that did not happen, which is the
one failure the whole quality package exists to prevent. It is repaired here rather
than recorded as a proposal, because the phase could not otherwise adopt the
dependency the owner chose, and because the repair is a scope parameter and a
missing finding rather than a design.

## Consequences

Six planned phases are now smaller than their titles suggest, and none of them says
so in `ROADMAP.md`. Whoever reaches 030, 260, 276, 280, 282 or 301 must read this
record to learn what already exists. That is the cost of an amendment that
displaces work, and it is paid six times here.

**GLOBIN now imports a runtime dependency for the first time.** `numpy` and
`pandas` were declared, locked and deliberately never imported;
`tests/architecture/test_stack_discipline.py` still enforces that. `psutil` is
imported, by exactly one adapter, and `tests/architecture/test_probe_discipline.py`
enforces *that*. The property "nothing GLOBIN ships depends on a third party at run
time" is gone, and it was worth something.

**GLOBIN now produces an artefact intended to leave the machine.** Everything
before this was written for GLOBIN or for CI. A support bundle is built to be sent
to somebody, which makes redaction a shipping property rather than a hygiene one.
[`../engineering/SUPPORT_BUNDLE.md`](../engineering/SUPPORT_BUNDLE.md) states what
can and cannot be guaranteed about it.

`docs/engineering/GPU_BENEFIT.md`, `docs/engineering/RUNTIME_HEALTH.md` and
`docs/engineering/SUPPORT_BUNDLE.md` become documents that must be kept true.

`zipfile` and `tracemalloc` join `[io] capable_modules`, tightening the layer
contract rather than loosening it.

The programme's fixity has now been amended eight times in twenty-four phases.
ADR-0016's warning — that a third amendment before Phase 016 would signal the
roadmap being treated as a backlog — has been passed four times over. This record
does not argue that the signal is wrong.

## Alternatives Considered

**Deliver the roadmap's Phase 024 alone, and record the brief as a proposal against
the phases that own it.** The course with no amendment, and the one
[`../engineering/SOURCE_OF_TRUTH.md`](../engineering/SOURCE_OF_TRUTH.md) points at.
Declined by the owner. Its real weakness was named when it was offered: with no
CUDA-capable library adopted, the harness alone records six workloads of which
three are baselines and three are `unavailable`, which is thin for a whole phase.

**Deliver the brief alone, retitling Phase 024.** Rejected because it displaces
*and* defers, and because nine artefacts name Phase 024 as the benchmark's owner —
one of them an ADR accepted in the previous commit. An accepted ADR is never
revised, so this would have meant superseding ADR-0060 to move a promise it had
just made.

**Deliver the harness plus only the seam no phase owns.** Offered as the middle
course: the GPU harness, plus a `diagnostics` command that snapshots and bundles
what already exists, with no process or host resource metrics (301's) and no
health-check suite semantics (030's). Declined by the owner. It would have needed
no new dependency at all.

**Reach for `ctypes` instead of adopting `psutil`.** Costed and put to the owner as
an explicit choice: `GlobalMemoryStatusEx`, `K32GetProcessMemoryInfo` and
`GetProcessHandleCount` are documented Win32 entry points and `ctypes` is already
in `[io] capable_modules`. The owner chose the dependency. What it buys is that a
wrong `ctypes.Structure` field width does not raise — it returns a plausible
number, which
[`../ARCHITECTURE_PRINCIPLES.md`](../ARCHITECTURE_PRINCIPLES.md) treats as worse
than a crash.

**Leave the runtime lock unreachable and hand-crank `pip lock` once.** Rejected
because it would have left the next person adding a runtime dependency at the same
wall, and would have left the gate unable to see the divergence that produced a
false `passed` here.

## Risks and Trade-offs

**The characteristic failure mode is that a `tolerates_unknown` flag becomes a way
to quieten a noisy check.** The aggregate forgives an unmeasurability that the
registry predicted, which is what stops a host without `psutil` from reporting
amber forever. The observable signal that it has been abused is a registry entry
whose tolerance nobody can explain in a sentence, and the mitigation is that the
flag lives in one visible table rather than being passed in by whoever builds the
snapshot.

**The second is that the bundle's allowlist rots into a denylist.** Today it is a
table with no directory walk anywhere, which is what makes the guarantee
reviewable. The signal that this was lost is a `glob` or an `iterdir` appearing in
the collector, at which point the property becomes "we excluded what we thought of".

**The third is that redaction is believed to cover more than it does.** It matches
field *names*. A credential inside an exception message or a free-text log line
survives, `faults.txt` is native traceback text nothing parses, and both
`SUPPORT_BUNDLE.md` and `RUNTIME_DIAGNOSTICS.md` say so. The signal that this was
forgotten is a phase putting a secret into a message on the grounds that the bundle
is redacted.

**The fourth is that a benchmark figure is read as a reproducible fact.** The
manifest separates measurements from verdicts and the determinism check covers only
the second, which is stated in three places. The signal that it was misread is
somebody comparing two `benchmark-manifest.json` digests and reporting drift.

Confidence is high on the archive, path-safety and atomic-publication semantics,
which are standard and were read from primary documentation
([`../research/phase_024_sources.md`](../research/phase_024_sources.md)). It is
moderate on the health model's shape, which has one consumer today and is being
designed for consumers in the two-hundreds. It is deliberately not stated as high
anywhere in this record's amendment reasoning, because the amendment reasoning is
the part that scored one of four.

## References

- [ADR-0016](0016-phase-004-absorbs-the-quality-gate-scope.md) — what a second amendment costs, and the warning about a third
- [ADR-0021](0021-phase-005-widens-to-include-the-test-foundation.md) — the four-part amendment test, restated above
- [ADR-0026](0026-correlation-is-bound-explicitly-not-ambiently.md) — the explicit-correlation rule this does not change
- [ADR-0032](0032-verification-tooling-may-be-added-outside-phase-scope.md) — the six conditions the benchmark gate is placed under
- [ADR-0045](0045-a-platform-capability-is-a-recorded-state-never-a-pass.md) — absence is a state, applied here to a library as well as a device
- [ADR-0051](0051-phase-017-absorbs-interpreter-pinning-and-the-environment-lifecycle.md) — the fourth amendment, the first to fail the test
- [ADR-0054](0054-the-toolchain-is-locked-with-pep-751-and-the-verdict-is-recomputed.md) — the lock gate this phase repaired
- [ADR-0056](0056-phase-021-widens-to-deliver-the-application-bootstrap.md) — the fifth amendment, and the bootstrap this extends
- [ADR-0057](0057-phase-022-widens-to-deliver-the-runtime-filesystem-and-lifecycle.md) — the sixth, and the runtime tree a bundle reads
- [ADR-0059](0059-the-mutable-runtime-tree-is-user-local-and-one-coordinator-is-proved-by-a-lock.md) — the lock semantics the health check reuses
- [ADR-0060](0060-gpu-capability-is-detected-and-the-runtime-explains-itself.md) — the seventh, which promised this phase the benchmark
- [ADR-0062](0062-workload-benefit-is-measured-and-a-timing-is-not-evidence-of-reproducibility.md) — the first half's decisions
- [ADR-0063](0063-a-support-bundle-is-allowlist-first-self-validating-and-atomically-published.md) — the second half's decisions
- [`../CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md) — the route the thirteen settings arrived through

## Supersedes

None.

## Superseded By

None.
