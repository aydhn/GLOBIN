# ADR-0029 — A severity threshold is a decorating sink, not a field on a sink or a check in the logger

## Status

Accepted — Phase 007.

**Date:** 2026-08-14

## Context

[`LOGGING_POLICY.md`](../LOGGING_POLICY.md) has said since Phase 006 that
severity carries no threshold and no filtering, that deciding which records are
worth keeping is a sink's concern, and that configuring it is Phase 007's work.
The module docstring of `src/globin/domain/observability.py` said the same. Phase
007 supplies the configuration, so the question of where the comparison happens
had to be answered rather than inherited.

`Severity` has been an `IntEnum` since Phase 006 specifically so that thresholds
would be comparisons — its docstring says so. Nothing had yet used that.

Three placements were available, and each is defensible enough that choosing
silently would have left the next contributor free to move it.

## Decision

**1. Filtering is `ThresholdLogSink`, a decorator implementing `LogSink` and
holding another `LogSink`.** It forwards a record when `event.severity >=
self.minimum` and drops it otherwise.

**2. `StreamLogSink` is unchanged.** It gains no field and no conditional. Phase
006's public type behaves exactly as it did.

**3. `Logger` is unchanged.** It does not know a threshold exists.

**4. The composition root wraps unconditionally**, not only when a threshold
above `DEBUG` has been configured. `DEBUG` is the lowest member, so at the
default the wrapper provably changes nothing.

**5. Dropping a record is deliberate data loss and is treated as such.**
[`ENGINEERING_CONTRACT.md`](../engineering/ENGINEERING_CONTRACT.md) invariant 22
permits it only as an explicit decision; the default threshold discards nothing,
so an operator has to ask in writing.

**What this does not cover.** Filtering by anything other than severity — by
event name, by correlation id, by sampling rate — is not decided here and has no
owner yet. A decorator is the shape such a thing would take, but nothing about
this record makes it desirable.

## Consequences

- A second sink can hold a different threshold: a file at `DEBUG` beside a
  console at `WARNING` needs no new type. That is the concrete payoff for not
  putting the comparison in `Logger`.
- The record is built even when it is dropped. Filtering in `Logger` would skip
  constructing the `LogEvent` entirely, and that cost is accepted: redaction and
  validation happen in `LogEvent.__post_init__`, so a record that is never built
  is also never checked, and a threshold would then decide which events get
  validated. Phases 081-096 will log from an order loop, and this is the trade to
  revisit if it ever measures.
- `build_logger` now returns a `Logger` whose sink is a `ThresholdLogSink`
  wrapping a `StreamLogSink`. Any caller asserting the concrete type of
  `build_logger(...).sink` would break; none does.
- Decision 4 means there is no branch in the composition root, and so no arm of
  one that nobody exercises.

## Alternatives Considered

**A `minimum` field on `StreamLogSink`.** Fewer objects, and the obvious first
idea. Rejected because it puts the policy in every sink implementation, so the
second sink is a second chance to forget it —
[ADR-0025](0025-structured-logging-is-a-redacted-domain-event.md) rejected
sink-side redaction with exactly this argument, and consistency here matters more
than one fewer object. It would also change a Phase 006 public type, and
`tests/unit/test_observability.py` constructs it positionally.

**A check in `Logger._emit`.** The fastest, because the event would never be
built. Rejected: `LOGGING_POLICY.md` calls filtering a sink's concern in the same
sentence that hands the job to this phase, and a logger that filtered would
decide for every sink it writes to. See *Consequences* for the cost accepted.

**A check in `LogEvent`.** Rejected outright — the domain would then need to know
a threshold, which is configuration, and
[`ENGINEERING_CONTRACT.md`](../engineering/ENGINEERING_CONTRACT.md) invariant 5
keeps that kind of state out of the core.

**Wrapping only when the threshold is above `DEBUG`.** Saves one object call per
record at the default. Rejected because it gives the composition root a decision
about *what* to build, which [ADR-0015](0015-single-composition-root-and-no-import-time-side-effects.md)
names in its own risk section as the signal that a composition root is turning
into a factory.

## Risks and Trade-offs

The characteristic failure mode is decoration becoming the answer to every
logging question. A decorator is cheap to add and each one is individually
reasonable, so a pipeline of five — threshold, sampler, rate limiter, enricher,
fallback — can assemble without anyone deciding to build a pipeline. At that
point the order of the decorators is load-bearing and nothing states it.

The observable signal is a second decorating sink arriving without an argument
about where it sits relative to this one, or a `build_logger` that has grown
enough parameters to need its own configuration section.

A smaller risk lies in decision 5's reasoning. The default discards nothing
today, so the invariant-22 argument costs nothing to honour. The first operator
who sets a threshold in production is choosing to lose records that no longer
exist anywhere, and neither this record nor
[`LOGGING_POLICY.md`](../LOGGING_POLICY.md) yet says whether a dropped record
should be counted. If Phases 289-304 want to know how much was discarded, that is
a new decision rather than a detail of this one.

## References

- [ADR-0025](0025-structured-logging-is-a-redacted-domain-event.md) — the port
  this decorator implements, and the argument reused here.
- [ADR-0026](0026-correlation-is-bound-explicitly-not-ambiently.md) — the
  companion record on what belongs in the adapter.
- [ADR-0027](0027-configuration-is-a-frozen-dataclass-validated-at-the-boundary.md)
  — where the threshold value comes from.
- [`../LOGGING_POLICY.md`](../LOGGING_POLICY.md) — the forward reference this
  record settles.
- [`../research/phase_007_sources.md`](../research/phase_007_sources.md) — entry
  S-03 on `IntEnum` ordering.

## Supersedes

None.

## Superseded By

None.
