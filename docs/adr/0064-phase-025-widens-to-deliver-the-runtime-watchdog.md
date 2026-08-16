# ADR-0064 — Phase 025 widens to deliver the runtime watchdog alongside TA-Lib

## Status

Accepted — Phase 025.

**Date:** 2026-08-17

## Context

[`ROADMAP.md`](../../ROADMAP.md) row 025 is *TA-Lib Native Library Provisioning*:
provision the native dependency the Python wrapper needs on Windows, with a
documented fallback. The owner's brief for this phase described something else — a
deterministic runtime watchdog: heartbeat and liveness registration, a suspect
threshold distinct from a confirmed stall, thread and deadlock evidence, a graceful
shutdown request, a bounded grace period and a fail-safe hard termination.

[`ROADMAP.md`](../../ROADMAP.md) row 263 is *Supervisor and Watchdog — detect hung
or dead components and recover them automatically*.

This is the **ninth** roadmap scope amendment. The eighth
([ADR-0061](0061-phase-024-widens-to-deliver-runtime-health-and-support-bundles.md))
closed by stating that a ninth *"inherits nothing from this one"*, and the seventh
([ADR-0060](0060-gpu-capability-is-detected-and-the-runtime-explains-itself.md))
had already required its successor to say which completed phase it overlaps. So
this argument cites neither, and cites no series.

The conflict was put to the owner with three courses — deliver both, deliver the
watchdog and displace TA-Lib to a later phase, or deliver TA-Lib alone and leave
the watchdog to Phase 263 — and the owner chose to deliver both.

## Decision

**1. Phase 025 delivers both halves.** It provisions and verifies TA-Lib as its
title requires, and it also delivers the in-process runtime watchdog: a monotonic
heartbeat registry, an eight-state machine, bounded and redacted stall evidence,
integration with Phase 022's shutdown latch, and a bounded escalation to
`ExitCode.WATCHDOG_STALLED`.

**2. It scores one of four against
[ADR-0021](0021-phase-005-widens-to-include-the-test-foundation.md), restated in
full rather than referenced.**

- *Nothing is deferred* — **passes.** TA-Lib ships, no other title changes, band
  ranges are untouched.
- *Nothing is displaced* — **fails.** Phase 263 owns hung-component detection, and
  parts of 030, 262, 266 and 302 arrive here.
- *No phase owns the work* — **fails**, and worse than the criterion above: Phase
  263 owns it **by title**, not merely in its purpose text. No previous amendment
  collided with a title.
- *The two halves need each other* — **fails.** A C indicator library and a liveness
  watchdog are unrelated. Either could have shipped alone and no gate refused until
  both existed.

**3. What it can say that its predecessors could not.** ADR-0060 demanded that the
eighth name the completed phase it overlaps; ADR-0061 answered *none*, and so does
this. Every phase this displaces — 030, 262, 263, 266, 302 — has not started.

What is new here is narrower and is the reason the collision with a title is
survivable: **the overlap with Phase 263 is refused rather than rebuilt.** Phase
263's verb is *recover*. This phase's verbs are *detect, record, request,
terminate*. Restarting a component, ordering a stop across subsystems, classifying
a failure, retrying, draining work in flight and reading the incident back after a
restart are all absent by design, and
[`../engineering/RUNTIME_WATCHDOG.md`](../engineering/RUNTIME_WATCHDOG.md) names
each with its owning phase. Terminating a process is not recovery; it is the
considered refusal of it.

**4. The watchdog is delivered on a seam and not on a driver.** No command starts
one, because no command is long-running and the long-lived process is Phase 257's
by name. This is the same shape Phase 022 left `build_lifecycle` in, and it is
stated in the documentation rather than discovered later.

**5. This licences nothing.** A tenth amendment inherits nothing from this one,
cannot cite the series, and — because this is the first to collide with a phase
*title* — must say whether it does the same and why that is acceptable if it does.

## Consequences

- `ROADMAP.md` carries a ninth entry in its *Scope amendments* block, and its
  count of amendments is repaired: the block said "seven" while listing eight, a
  drift Phase 024 introduced and nothing tested.
- Phase 025's purpose text says it delivers both halves, so the size of the phase
  is visible in the roadmap rather than only in the diff.
- `ta-lib` leaves `docs/engineering/wheel-survey.toml` for
  `docs/engineering/stack-contract.toml`, and `DELIVERED_PHASE` rises 22 → 25 in
  both the wheels and stack gates. Raising the second one found a stale deferral
  that had been false since Phase 023 shipped.
- Phase 263's brief is narrower than it was: detection exists, so what remains
  there is recovery.
- A third configuration section, a new exit code, a new engineering document and
  the first thread GLOBIN starts all arrive in one phase.

## Alternatives Considered

**Deliver the watchdog and displace TA-Lib.** Rejected by the owner. It would have
been the first retitle-with-displacement since the second amendment, and TA-Lib
would have had to be rehoused — Phase 114 already names it, so the move was
possible, but it would have traded a criterion this amendment passes (*nothing
deferred*) for one it fails.

**Deliver TA-Lib alone and leave the watchdog to Phase 263.** Rejected by the
owner. It is the only course that scores four of four, and its cost is that a
process which can wedge silently stays that way for 238 phases.

**Deliver the watchdog as tooling beside the phase under
[ADR-0032](0032-verification-tooling-may-be-added-outside-phase-scope.md).** Rejected
here rather than by the owner: that mechanism is for tooling that acts on the
repository, and a watchdog is product code that ships inside the application.

## Risks and Trade-offs

**The characteristic failure mode is that Phase 263 arrives and finds its subject
half-built in a way that does not fit.** This phase chose an in-process,
single-process, no-recovery design; a supervisor may want cross-process liveness
and a different heartbeat shape, and would then have to either wrap this or
replace it.

**The observable signal** is Phase 263 proposing to rewrite
`globin.domain.watchdog` rather than to build on it. If that happens, the right
reading is not that the watchdog was wrong but that delivering it early cost a
design conversation that Phase 263 existed to have.

**A second risk is size.** Nine amendments in twenty-five phases means the roadmap
is being treated as a plan that reality edits, which
[ADR-0016](0016-phase-004-absorbs-the-quality-gate-scope.md) warned about at three.
The signal that this has gone wrong is a tenth amendment before the band closes at
Phase 032; the right response then is to question the roadmap's granularity rather
than to write an eleventh argument.

## References

- [`../../ROADMAP.md`](../../ROADMAP.md) — rows 025, 114 and 263, and the scope
  amendment block.
- [ADR-0021](0021-phase-005-widens-to-include-the-test-foundation.md) — the four
  criteria.
- [ADR-0060](0060-gpu-capability-is-detected-and-the-runtime-explains-itself.md),
  [ADR-0061](0061-phase-024-widens-to-deliver-runtime-health-and-support-bundles.md)
  — the constraints placed on this amendment by its predecessors.
- [ADR-0065](0065-liveness-is-monotonic-and-escalation-is-bounded-from-the-stall.md)
  — the watchdog's own contract.
- [`../research/phase_025_sources.md`](../research/phase_025_sources.md) — the
  external evidence both halves rest on.

## Supersedes

None.

## Superseded By

None.
