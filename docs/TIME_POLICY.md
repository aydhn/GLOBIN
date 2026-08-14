# Time Policy

How GLOBIN says *when*: which types exist, what each refuses, where a clock may
be read, and what happens to the microseconds a venue does not want.

This document owns the register. The behaviour lives in
[`globin.domain.clock`](../src/globin/domain/clock.py), and
`tests/contract/test_clock_contract.py` compares the two in both directions —
executing each documented conversion rather than matching strings, so neither
this document nor the code can drift without a test noticing.

The rule this policy makes enforceable is
[`ENGINEERING_CONTRACT.md`](engineering/ENGINEERING_CONTRACT.md) invariant 25:
*timezone-naive datetimes must not cross a domain boundary, internal time is
UTC, and wall-clock time is an input to be injected.* Phase 006 committed the
logging half of it ([ADR-0026](adr/0026-correlation-is-bound-explicitly-not-ambiently.md));
Phase 009 states it generally.

---

## Why time is injected

Reading a clock is the purest form of ambient nondeterminism: the same code
returns a different answer every time, and nothing in the call site says so. A
component that reads the clock itself cannot be tested without freezing
something global, and freezing something global is the shared mutable state
invariant 5 forbids.

So GLOBIN inverts it. Nothing outside the adapters layer reads a clock. A
component that needs the time is handed a [`Clock`](../src/globin/ports/clock.py)
and asks it, and a test hands it a clock that answers whatever the test needs.

This is enforced rather than encouraged. `tests/architecture/test_clock_discipline.py`
parses every module in the domain, ports and application layers and refuses a
call to `datetime.now`, `time.monotonic`, `date.today` and their relatives —
anywhere in the module, including inside a function body.

Two existing checks look as though they would already catch this, and neither
does. The dependency contract forbids an inner layer importing an I/O-capable
module, and `time` joined that list in Phase 009 — but `datetime` deliberately
did not, because invariant 25 presupposes that *aware* datetimes cross a domain
boundary, so the domain must be able to name the type. Ruff's `DTZ` rules refuse
naive constructions repository-wide, which is about *awareness* and never about
*location*: `datetime.now(UTC)` in the domain layer passes them cleanly.

---

## The types

| Type | Carries | Refuses |
|---|---|---|
| `Instant` | A moment, as a timezone-aware UTC `datetime` | A naive datetime, a `date`, a non-UTC offset, a `tzinfo` that cannot report one |
| `Duration` | A length of time, in whole nanoseconds | A negative count, a `bool`, anything that is not an `int` |
| `MonotonicReading` | One reading of a monotonic clock, in nanoseconds from an undefined origin | A `bool`, anything that is not an `int` |

`Instant` is the only one that denotes a calendar moment. `Duration` is a length
rather than a position. `MonotonicReading` denotes neither on its own — see
*Wall time and monotonic time* below.

An aware datetime at another offset is **converted** by
[`instant()`](../src/globin/domain/clock.py), not refused: it names an
unambiguous moment, so converting it is arithmetic rather than a guess. A naive
one is refused for the opposite reason — nothing in the value says whether it
means UTC, the host's zone, or the zone of whoever wrote it down.

---

## The bounds, as constants

| Constant | Value |
|---|---|
| `MICROSECONDS_PER_MILLISECOND` | `1000` |
| `MICROSECONDS_PER_SECOND` | `1000000` |
| `MICROSECONDS_PER_DAY` | `86400000000` |
| `NANOSECONDS_PER_MILLISECOND` | `1000000` |
| `MIN_EPOCH_MILLIS` | `-62135596800000` |
| `MAX_EPOCH_MILLIS` | `253402300799999` |

The two epoch bounds are the calendar's own limits — `0001-01-01T00:00:00Z` and
`9999-12-31T23:59:59.999Z` — written as literals because building a `datetime`
at module level is a call, and the architecture suite refuses any call performed
when a layer package is imported. A unit test derives both and compares, so the
literals cannot drift from what they claim to be.

There is deliberately **no plausibility bound**. A timestamp in 1970 or in 3000
is admitted. Phase 008 needed `MAX_ADJUSTED_EXPONENT` because `Decimal` is
unbounded and could render a hundred-thousand-character string; `datetime` is
already bounded to four-digit years, so the hazard does not exist here. "No
timestamp before the exchange launched" is a claim about the world, not about
the shape of a value, and validation here is context-free.

---

## Which operations exist

| Attempt | Outcome |
|---|---|
| `instant < instant` | answers |
| `instant == instant` | answers |
| `instant == duration` | answers |
| `instant < datetime` | TypeError |
| `instant - instant` | TypeError |
| `instant + duration` | TypeError |
| `float(instant)` | TypeError |
| `reading.since(earlier)` | answers |
| `earlier.since(reading)` | ValidationError |
| `reading.since(instant)` | ValidationError |
| `reading - reading` | TypeError |
| `duration + duration` | TypeError |
| `duration < duration` | answers |

**`Instant` orders and never refuses.** There is exactly one denomination for
wall time, which is what this phase establishes. That is the deliberate contrast
with [`VALUE_TYPES_POLICY.md`](VALUE_TYPES_POLICY.md), where two `Price` values
can share a type and still be incomparable: a price carries a market, and
comparing across markets raises.

**`Instant` defines no subtraction, and this is the phase's counterpart to
"compare but do not compute".** The difference between two wall-clock readings
is not an elapsed time. `time.time()` "can return a lower value than a previous
call if the system clock has been set back", and on the declared host
`time.get_clock_info('time')` reports `adjustable=True`. An operator that
silently returned a `Duration` would make the wrong measurement easy to write
and impossible to notice — the failure would be a quietly wrong latency, not an
exception. Elapsed time is the monotonic clock's job.

A caller that genuinely wants a wall-clock difference — Phase 040, measuring
skew against server time — subtracts one `epoch_millis` from another, which is
explicit and visibly a wall-clock difference.

---

## Wall time and monotonic time

They answer different questions under incompatible guarantees, so they are two
ports rather than one port with two methods.

| | `Clock` | `MonotonicClock` |
|---|---|---|
| Answers | at what moment | how much time passed |
| Can go backwards | yes — an operator or an NTP correction can step it | no |
| Means anything alone | yes | no — the reference point is undefined |
| Adapter | `SystemClock`, via `datetime.now(UTC)` | `SystemMonotonicClock`, via `time.monotonic_ns()` |

A `MonotonicReading` cannot be rendered as a time and cannot produce epoch
milliseconds. That absence is the type doing its job: the standard library
documents the reference point as undefined "so that only the difference between
the results of two calls is valid", so a conversion to a calendar moment would
claim a correspondence the platform does not promise.

Two readings from different clock instances, or from different processes, are
not comparable either. Nothing in the code can detect that, which is stated here
rather than pretended away.

`monotonic_ns` rather than `perf_counter_ns` is a contract choice, not a
resolution one. On the declared host the two are the same source —
`QueryPerformanceCounter()` at `1e-07` resolution for both — so the choice costs
nothing measurable here. It is made on the guarantee, because the declared host
is not the only machine this will ever run on.

The second port has no consumer yet. It exists because `ROADMAP.md` gives Phase
009 "monotonic clocks" by name, and because the decision worth fixing now is
which guarantee an elapsed measurement rests on.

---

## Milliseconds

Binance publishes every timestamp field in milliseconds by default. A `datetime`
carries microseconds. The conversion therefore discards information, and the
direction is a decision rather than an accident.

**`epoch_millis` floors, towards the past.**

Four reasons, in order of force:

1. **A floored instant has happened; a rounded-up one has not.** Rounding to
   nearest, or up, can name a millisecond in the future. For a value that will
   eventually be compared against an exchange's `recvWindow`, a timestamp that
   has drifted forward is the one that gets rejected.
2. **Floor never moves an instant forward, and moves it by less than one
   millisecond.** That is a testable bound, and it is the property that
   distinguishes flooring from every rounding mode — monotonicity alone does
   not, because round-half-even is monotone too.
3. **It is what `//` already does.** No sign branch, no half-way tie rule
   imported from a domain where it belongs.
4. **It is a projection, not arithmetic.** Nothing in the path touches
   `Decimal` or reads `decimal.getcontext()`.

Flooring is towards the past on both sides of the epoch, because Python's `//`
floors rather than truncating towards zero. Pre-1970 instants are not something
GLOBIN trades on; a conversion that changed direction at the epoch would be a
latent surprise rather than a decision.

The reverse projection is exact: a whole number of milliseconds round-trips
through `instant_from_epoch_millis` and back unchanged.

The internal representation stays at microsecond resolution. Storing epoch
milliseconds and deriving the datetime would truncate at the door, and
[`ENGINEERING_CONTRACT.md`](engineering/ENGINEERING_CONTRACT.md) invariant 22
forbids silent data loss. The venue convention is a property of the wire, not of
GLOBIN. Sub-millisecond instants are therefore **not** refused — the system clock
produces them — and the loss is named rather than prevented.

### This is not the rounding policy Phase 010 owns

The collision is superficially plausible and worth answering directly.

Phase 010 owns *decimal arithmetic*: where `Decimal` is mandatory versus float,
and how tick and step sizes round. It is delivered, in
[`PRECISION_POLICY.md`](PRECISION_POLICY.md). Its subject is money-shaped
magnitudes whose rounding is a financial decision — a tick size is set by a
venue, and a rounding mode changes what you pay.

This is integer floor division between two exact integer grids, microseconds to
milliseconds. It constructs no `Decimal` and reads no thread-local context, so
it is immune to the hazard that is Phase 010's entire reason for existing.

In one sentence: **Phase 010 decides how a magnitude rounds; Phase 009 decides
how a coordinate is projected onto a coarser grid.** A magnitude's rounding
changes the quantity. A coordinate's projection changes the resolution at which
it is named.

The failure mode, if the two are ever confused, is someone writing
`Decimal(micros) / 1000`. That single line would put the millisecond convention
under the ambient decimal context and make it Phase 010's problem retroactively.

---

## What this policy does not decide

| Question | Owning phase |
|---|---|
| Where exact decimal arithmetic is mandatory, and how prices round | 010, delivered — [`PRECISION_POLICY.md`](PRECISION_POLICY.md) |
| Canonical identifiers for runs and orders | 011, delivered — [`IDENTIFIER_POLICY.md`](IDENTIFIER_POLICY.md) |
| How a timestamp is serialised and how that format may evolve | 012 |
| Server time synchronisation, drift measurement and the response to skew | 040 |
| Scheduling, intervals and anything that waits | 257-272 |

Phase 040 is the important one. GLOBIN has two independent time sources — this
host's clock and the venue's server time — and this policy governs only the
first. Reconciling them, and deciding what to do when they disagree, is not
decided here. Nothing reaches a venue yet.

---

## Related documents

| Question | Document |
|---|---|
| Why is time injected rather than read? | [ADR-0034](adr/0034-time-is-injected-and-internal-time-is-utc.md) |
| Why do milliseconds floor? | [ADR-0035](adr/0035-milliseconds-are-a-floored-projection.md) |
| Why does the log record carry no timestamp? | [ADR-0026](adr/0026-correlation-is-bound-explicitly-not-ambiently.md) |
| What must all code satisfy? | [`ENGINEERING_CONTRACT.md`](engineering/ENGINEERING_CONTRACT.md) |
| How are prices and quantities expressed? | [`VALUE_TYPES_POLICY.md`](VALUE_TYPES_POLICY.md) |
| Where did these facts come from? | [`research/phase_009_sources.md`](research/phase_009_sources.md) |
