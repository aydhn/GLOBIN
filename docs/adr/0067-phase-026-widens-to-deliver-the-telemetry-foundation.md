# ADR-0067 — Phase 026 widens to deliver the telemetry foundation, and this is the tenth amendment

## Status

Accepted — Phase 026.

**Date:** 2026-08-17

## Context

[`ROADMAP.md`](../../ROADMAP.md) row 026 is *Configuration File Layout and
Profiles*: define on-disk configuration locations and the paper, demo, testnet and
live profile structure. The owner's brief for this phase described something else —
a vendor-neutral runtime telemetry foundation: a typed contract, a metric registry,
low-cardinality attribute governance, context propagation, a bounded exporter and
deterministic telemetry evidence.

[`ROADMAP.md`](../../ROADMAP.md) row 280 is *Operational Metrics Collection —
collect health, latency, throughput and error metrics locally*. Row 315 is *Live
Monitoring and Escalation*.

This is the **tenth** roadmap scope amendment. The ninth
([ADR-0064](0064-phase-025-widens-to-deliver-the-runtime-watchdog.md)) placed two
constraints on it, and both are obeyed here rather than cited as precedent. It
required that a tenth *"inherits nothing from this one, cannot cite the series,
and — because this is the first to collide with a phase title — must say whether it
does the same and why that is acceptable if it does."* And its Risks section named
this exact event: *"The signal that this has gone wrong is a tenth amendment before
the band closes at Phase 032; the right response then is to question the roadmap's
granularity rather than to write an eleventh argument."*

The conflict was put to the owner with four courses — deliver both, deliver the
roadmap's phase alone, deliver telemetry alone and displace the configuration
layout, or add telemetry as tooling under
[ADR-0032](0032-verification-tooling-may-be-added-outside-phase-scope.md). He chose
to deliver both, and separately chose the OpenTelemetry and Prometheus dependency
scope with the transitive cost stated in advance.

## Decision

**1. Phase 026 delivers both halves.** It defines the on-disk configuration
locations and the four profiles its title requires, and it also delivers the
telemetry foundation: a provider-neutral typed contract, a metric registry with
cardinality bounded by construction, span values with `contextvars` propagation, a
bounded and failure-safe delivery path, two provider bridges, a configuration
section and a read-only CLI surface.

**2. It scores one of four against
[ADR-0021](0021-phase-005-widens-to-include-the-test-foundation.md), restated in
full rather than referenced.**

- *Nothing is deferred* — **passes.** The configuration layout ships whole. No
  other title changes, and the band ranges are untouched.
- *Nothing is displaced* — **fails.** Phase 280 owns local metrics collection, and
  parts of 282 and 315 arrive here.
- *No phase owns the work* — **fails, and by title.** Phase 280 owns it as
  *Operational Metrics Collection*.
- *The two halves need each other* — **fails.** A configuration file layout and a
  telemetry foundation are unrelated. Either could have shipped alone and no gate
  would have refused until both existed.

**3. Yes, it collides with a phase title, and it is the second consecutive
amendment to do so.** ADR-0064 demanded this be stated rather than left for a
reader to notice. The ninth collided with Phase 263's title; this collides with
Phase 280's. **That is materially worse than a repeat of an earlier shape**, and
this record says so rather than treating it as normalised.

**4. What it can say that its predecessors could not.** It overlaps **no completed
phase**. Every phase it displaces — 280, 282, 315 — has not started.

The collision with 280 is **refused rather than rebuilt**, which is the shape
ADR-0064 used for Phase 263 and is the only reason a title collision is survivable.
Phase 280's verb is *collect*. This phase's verbs are *declare*, *bound* and
*record*. Absent by design and named with their owning phases in
[`../engineering/RUNTIME_TELEMETRY.md`](../engineering/RUNTIME_TELEMETRY.md):
collection from real trading subsystems, retention, aggregation across runs,
dashboards, alerting, and any instrumentation of a Binance transport.

**5. Both halves are delivered on a seam and not on a driver.**
`build_configuration` still passes no sources, and no command starts a telemetry
collector. Production behaviour is unchanged by both halves. The *shape* is the one
ADR-0064 §4 used; the amendment it belongs to is not cited.

**6. The signal ADR-0064 named has fired, and the response is stated here rather
than deferred.** This is the tenth amendment and it arrives at Phase 026, six
phases before the band closes. **Phase 032 — the environment band's consolidation
and gate review — must examine whether Phases 017-032 were drawn at a granularity
that describes the work, and must do so with all ten amendments in front of it
rather than with a prediction.** An eleventh amendment before Phase 032 is not
another argument to be weighed; it is evidence that the roadmap's granularity is
itself the defect.

**7. This licences nothing.** An eleventh inherits nothing from this record, cannot
cite the series, and — because a title collision has now happened twice running —
must additionally say whether title collisions have become the norm. If it cannot
answer no, it should be refused rather than argued.

## Consequences

- `ROADMAP.md` carries a tenth entry in its scope-amendment block and its count
  rises nine → ten.
- Four runtime dependencies are adopted with written reviews, and `pylock.toml`
  grows from eleven distributions to twenty-six. The owner was given that number
  before choosing.
- `DEFAULT_PROFILE` changes from `"default"` to `"paper"`, so `run/instance.json`
  and every health snapshot record a different value than they did.
- `config/` exists, filling the `RuntimePaths.config` reservation Phase 021
  declared and `REPOSITORY_LAYOUT.md` has been holding open.
- A fourth configuration section arrives, taking the register from twenty-two
  settings to twenty-nine.
- GLOBIN gains its **second** thread, and its **first ability to bind a socket** —
  the latter off by default, loopback-only, and enforced by an architecture test.
- **No `DELIVERED_PHASE` constant rises**, and the reason is recorded because the
  reflex is to bump them: the wheel survey's floor bounds *survey entries*, of
  which the lowest remaining names phase 045, and the stack gate's floor bounds
  *deferrals*, of which the lowest names 097. Both are floors rather than mirrors,
  and a constant bumped to silence a test is a constant nobody reads.
- Phase 280's brief is narrower than it was: the vocabulary and the bounds exist,
  so what remains there is collection.

## Alternatives Considered

**Deliver the configuration layout alone and leave telemetry to Phase 280.** The
only course scoring four of four against ADR-0021, and the most defensible reading
of `MEMORY.md`'s standing instruction. Rejected by the owner. Its cost is that
nothing in GLOBIN can measure itself for 254 phases.

**Deliver telemetry and displace the configuration layout.** Rejected by the owner.
It would trade the one criterion this amendment passes — *nothing deferred* — for
one it already fails, and Phase 027 depends on 026's layout immediately, so the
displacement would have propagated.

**Add telemetry as tooling under [ADR-0032](0032-verification-tooling-may-be-added-outside-phase-scope.md).**
Rejected here rather than by the owner. That mechanism's fourth condition is that
the addition *"adds no runtime capability"*, and a telemetry API under
`src/globin/` is nothing but runtime capability. Calling it tooling would be the
sentence ADR-0032 exists to make visible.

**Deliver the vocabulary only, and leave the exporter to Phase 280.** Considered
and not put to the owner, because it fails on its own terms: a contract nothing
exercises is a contract nobody has checked, and the delivery state machine is
where the interesting refusals live.

## Risks and Trade-offs

**The characteristic failure mode is that Phase 280 arrives and finds its subject
half-built in a shape that does not fit.** This phase chose an in-process,
single-process, snapshot-oriented design with a fixed registry. A collector may
want a different instrument lifecycle, per-process aggregation, or names declared
by the subsystems that own them rather than centrally.

**The observable signal** is Phase 280 proposing to rewrite `globin.domain.metrics`
rather than build on it. If that happens, the right reading is not that the
telemetry model was wrong but that delivering it early cost a design conversation
Phase 280 existed to have.

**The second risk is the one this record cannot mitigate, only name.** Ten
amendments in twenty-six phases means the roadmap is being treated as a plan that
reality edits — which [ADR-0016](0016-phase-004-absorbs-the-quality-gate-scope.md)
warned about at three, and which ADR-0064 predicted would show itself here. Decision
6 is a commitment rather than a note: Phase 032 examines the granularity, with the
evidence rather than with a forecast.

**A third risk is size.** This phase adds four dependencies, seven source modules,
eleven test modules, three ADRs and a socket-binding capability. A phase that large
is one whose review is harder than any of its parts, and that is a cost paid at
review time rather than at design time.

## References

- [`../../ROADMAP.md`](../../ROADMAP.md) — rows 026, 280, 282, 315, and the scope
  amendment block.
- [ADR-0021](0021-phase-005-widens-to-include-the-test-foundation.md) — the four
  criteria, restated in full above.
- [ADR-0064](0064-phase-025-widens-to-deliver-the-runtime-watchdog.md) — the two
  constraints this record obeys, and the prediction it confirms.
- [ADR-0068](0068-telemetry-is-provider-neutral-and-cardinality-is-bounded-by-construction.md)
  — the telemetry contract itself.
- [ADR-0069](0069-configuration-is-derived-rather-than-searched-and-a-profile-names-a-document.md)
  — the configuration layout.
- [`../research/phase_026_sources.md`](../research/phase_026_sources.md) — the
  external evidence both halves rest on.

## Supersedes

None.

## Superseded By

None.
