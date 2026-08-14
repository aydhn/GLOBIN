# ADR-0035 — Milliseconds are a floored projection, not the representation

## Status

Accepted — Phase 009.

**Date:** 2026-08-14

## Context

`ROADMAP.md` gives Phase 009 "millisecond conventions" by name. The convention
exists because of one external fact: Binance publishes every time and timestamp
field in milliseconds by default, with microseconds available only behind a
request header. GLOBIN's internal representation is a `datetime`, which carries
microseconds.

So a conversion between the two loses information, and something has to decide
in which direction. Left undecided, the answer becomes whatever the first
implementation happened to write, and the second implementation disagrees.

There is a second question underneath, and it is the one a future reader is more
likely to raise: **does this collide with Phase 010?** That phase owns
"where decimal arithmetic is mandatory versus floating point, and rounding and
tick-size behaviour". Both look like rounding decisions. If they are the same
question, Phase 009 has pre-empted a later phase, which `ROADMAP.md` rule 5
calls a defect.

## Decision

**1. The representation is microsecond-resolution aware UTC.** Epoch
milliseconds are a *projection*, produced on demand by `Instant.epoch_millis`,
never the stored form. Storing milliseconds would truncate at the door, and
`ENGINEERING_CONTRACT.md` invariant 22 forbids discarding data silently.

**2. The projection floors, towards the past**, computed by integer floor
division. Four reasons, in order of force:

- A floored instant has happened; a rounded-up one has not. Rounding to nearest
  or up can name a millisecond in the future, and for a value that will
  eventually be compared against an exchange's `recvWindow`, a timestamp that
  has drifted forward is the one that gets rejected.
- Floor never moves an instant forward, and moves it by less than one
  millisecond. That is a testable bound, and it is what distinguishes flooring
  from every rounding mode — monotonicity alone does not, because round-half-even
  is monotone too. `tests/property/test_clock_properties.py` asserts the bound
  rather than the mechanism.
- It is what `//` already does: no sign branch, no tie-break rule imported from a
  domain where it belongs.
- It is a projection, not arithmetic. Nothing in the path constructs a `Decimal`
  or reads `decimal.getcontext()`.

**3. Flooring is towards the past on both sides of the epoch.** Python's `//`
floors rather than truncating towards zero, and that behaviour is kept rather
than special-cased. Pre-1970 instants are not something GLOBIN trades on; a
conversion that changed direction at the epoch would be a latent surprise.

**4. The reverse projection is exact.** A whole number of milliseconds
round-trips through `instant_from_epoch_millis` and back unchanged, over the
entire representable range.

**5. `Duration.milliseconds` obeys the same law**, from nanoseconds. One
convention in the phase, at two call sites.

**6. Sub-millisecond instants are not refused.** The system clock produces them,
so refusing them would make every log call raise. The loss is named rather than
prevented — which is what invariant 22 actually requires.

**7. This does not decide anything Phase 010 owns.** Phase 010's subject is
decimal magnitudes whose rounding is a financial decision: a tick size is set by
a venue, and a rounding mode changes what you pay. This is integer floor
division between two exact integer grids. In one sentence: **Phase 010 decides
how a magnitude rounds; Phase 009 decides how a coordinate is projected onto a
coarser grid.** A magnitude's rounding changes the quantity; a coordinate's
projection changes the resolution at which it is named.

## Consequences

A logged ISO timestamp and a persisted millisecond value will disagree in their
last three digits for the same instant. That is correct and is stated in
`TIME_POLICY.md`, but it will surprise somebody comparing the two by eye.

Nothing in GLOBIN may convert time through `Decimal`. The line
`Decimal(micros) / 1000` would put this convention under the ambient decimal
context and make it Phase 010's problem retroactively. There is no test that
catches that line; `TIME_POLICY.md` states the rule so it is refusable at review.

Phase 012, which owns serialization, inherits a settled answer rather than an
open question: the wire form of an instant is a whole number of milliseconds and
the projection is total in both directions.

## Alternatives Considered

**Round half to even.** The statistically unbiased choice, and the default for
`Decimal`. Rejected because it can name an instant that has not happened yet,
and because it imports a tie-break rule from the domain where ties matter —
money — into one where they do not.

**Round up.** Rejected for the same reason as half-even, more so: it moves
*every* inexact instant forward.

**Refuse a sub-millisecond instant.** Fail-closed, and superficially in keeping
with Phase 008's refusal-heavy style. Rejected because `SystemClock` produces
microsecond-resolution instants, so every single log call would raise. Phase
008's refusals reject values a caller *should not* have constructed; this would
reject the values the system itself produces.

**Store milliseconds and drop microseconds at construction.** Simplest possible
model, and the wire form and the internal form would then be identical.
Rejected under invariant 22 — see ADR-0034, which owns the representation
question this depends on.

**Defer the whole question to Phase 010.** The most conservative reading of the
phase boundary. Rejected because it would ship a phase whose stated deliverable
is "millisecond conventions" without any, and because Phase 010's subject is
decimal magnitudes rather than time coordinates — inheriting its rounding mode
would be the cross-contamination the deferral is meant to avoid. Floor is right
for a coordinate and very often wrong for a price.

## Risks and Trade-offs

**The characteristic failure is the two rounding questions merging.** Somebody
reads "GLOBIN floors" as a general rule and applies it to a price. The
observable signal is a rounding mode appearing in Phase 010's work that cites
this record rather than arguing from tick sizes. The countermeasure is the
one-sentence distinction above, which is stated in both this record and
`TIME_POLICY.md` precisely so it can be quoted back.

**The floor is invisible in a log line.** A record shows microseconds; the
millisecond value derived from it is silently three digits shorter. A property
test bounds the gap at under one millisecond, but nothing surfaces it at the
point of use.

**If a later phase genuinely needs half-even for time**, it supersedes this
record rather than adding a mode argument. A conversion with a mode is a
conversion whose behaviour depends on the caller, which is how one convention
becomes two.

## References

- [`../TIME_POLICY.md`](../TIME_POLICY.md) — the convention as a register
- [ADR-0034](0034-time-is-injected-and-internal-time-is-utc.md) — the representation this projects from
- [`../engineering/ENGINEERING_CONTRACT.md`](../engineering/ENGINEERING_CONTRACT.md) — invariants 17 and 22
- [`../research/phase_009_sources.md`](../research/phase_009_sources.md) — the Binance and Python facts relied on
- [`../../ROADMAP.md`](../../ROADMAP.md) — Phase 010, which owns decimal precision

## Supersedes

None.

## Superseded By

None.
