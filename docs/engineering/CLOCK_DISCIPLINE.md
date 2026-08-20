# Clock Discipline

How GLOBIN decides what time the venue thinks it is, how sure it is of that, and
what it refuses to do when it is not sure enough.

This document owns the prose. The behaviour lives in
[`globin.domain.clock_sync`](../../src/globin/domain/clock_sync.py), the thresholds
are declared in [`clock-contract.toml`](clock-contract.toml), and
`tests/contract/test_clock_sync_contract.py` compares all three — in both directions, so
neither this document, the contract, nor the code can drift without a test noticing.

Phase 036 delivered it. What it deliberately does not do is in
[What this phase did not do](#what-this-phase-did-not-do).

---

## Why the host's wall clock is not a signing clock

Binance rejects a signed request whose timestamp is outside a window it computes
against **its own** clock. GLOBIN has no access to that clock; it has a Windows
host clock, and `time.get_clock_info('time')` reports `adjustable=True` for it on
the declared host. Three ordinary events move it:

- the Windows Time Service correcting drift, which it does on a schedule;
- an NTP step after a long sleep or a network change;
- an operator changing the date.

None of those announces itself. A process that read the wall clock and signed with
it would keep working until one of them happened, and would then produce
timestamps the venue refuses — or, worse, timestamps the venue *accepts* that
describe a moment the request was not made in.

So GLOBIN does not sign with the host clock. It signs with the host clock **plus a
measured correction**, and refuses to sign at all when that correction is missing,
old, or too uncertain to be worth applying.

---

## Wall time and monotonic time

Two clocks, two guarantees, and the whole estimator depends on using each for what
it promises. [`TIME_POLICY.md`](../TIME_POLICY.md) states the split; this is what
the clock layer does with it.

| | wall clock | monotonic clock |
|---|---|---|
| Answers | at what moment | how much time passed |
| Can be stepped | **yes** | no |
| Used here for | the calibration anchor, the timestamp | the round trip, the sample age, jump detection |

Every elapsed interval in this layer is monotonic. A sample's *age* is monotonic,
so correcting the host clock does not make a stale calibration look fresh. A round
trip is monotonic, so an NTP step landing mid-request cannot inflate or shrink it.

The one wall reading that matters is the **anchor**, taken once immediately before
a request goes out. The midpoint is then computed by extending that single anchor
along a monotonic span — never by subtracting two wall readings, which is what
would let a mid-flight correction enter the offset directly.

---

## The estimator

One exchange produces one sample:

```text
anchor   = clock.now()          one wall read
started  = monotonic.reading()  taken adjacently
   → GET /api/v3/time →
finished = monotonic.reading()

round_trip     = finished - started
local_midpoint = anchor + round_trip / 2
offset         = serverTime - local_midpoint
uncertainty    = round_trip / 2
```

### Why a midpoint

The venue stamps its answer at an unknown moment between GLOBIN's send and
GLOBIN's receive. The naive estimate — `serverTime - now_at_receive` — assumes it
stamped at receive time, and therefore attributes the **entire** round trip to the
offset. On a 200 ms link, a host with a perfect clock would measure itself 200 ms
fast and then correct itself into being 200 ms wrong.

The midpoint assumes the path is symmetric. That is not always true, and when it is
not the estimate is wrong by at most half the round trip. **That bound is carried
rather than forgotten**: it is `uncertainty`, and every gate downstream is expressed
in terms of it.

### Why the lowest round trip wins

The window keeps the last five samples and the estimator selects **one** of them —
the fastest — rather than combining them. Two independent reasons:

1. **The bound.** A midpoint estimate is wrong by at most half its round trip, so
   the fastest exchange is by definition the tightest estimate in the window.
   Averaging produces a number whose error is governed by the *slowest* sample
   included; it cannot be tighter than the minimum and is usually looser.
2. **The transport.** `HttpRestTransport` pools connections. The **first** exchange
   on a fresh pool pays a TCP and TLS handshake before any request is written, so
   its elapsed time is not a round trip at all and the venue stamps its answer
   nowhere near the middle of it. An averaging estimator folds that handshake into
   the offset. Selecting the minimum discards it structurally, without needing to
   know which sample was first.

A median over a low-round-trip subset was considered and declined in
[ADR-0093](../adr/0093-server-time-is-estimated-from-the-lowest-round-trip-and-a-window-is-never-widened.md):
it costs a sort and a tie rule and improves no bound.

Ties go to the later sample — the fresher measurement of the same quality — so two
runs over one window always agree.

---

## Clock domains

A calibration is per **clock domain**, never global. A domain is three facts:

```text
family / environment / protocol        e.g. spot/testnet/rest
```

Production and testnet are different machines. A round trip to one says nothing
about the offset of the other, and borrowing an estimate across that boundary would
be reporting a measurement that was never taken. The type is built from Phase 033's
own identifier types, so this layer enumerates no product and names no environment —
which is what `tests/architecture/test_identifier_discipline.py` requires.

**24 domains are declared and 3 can be calibrated.** Only Spot has a
documented REST surface in
[`binance-api-reality.toml`](binance-api-reality.toml); the other seven families
record `unknown` and carry no endpoint, because their documentation is
client-rendered and [`SOURCE_POLICY.md`](../SOURCE_POLICY.md) forbids both scraping
it and accepting a summary in its place. So `/fapi/v1/time`, `/dapi/v1/time` and
`/eapi/v1/time` are spelled **nowhere** in this package. The domains are named and
asking them anything refuses:

```text
$ globin clock calibrate --family usds_m_futures --environment production
  REFUSED  usds_m_futures/production/rest
           the REST surface for usds_m_futures is recorded as unknown, not supported
  Nothing was sent.
```

That is a measurement rather than a gap. The day the registry gains a row, the
domain becomes calibratable with no change to this layer.

---

## Precision

The venue documents `timestamp` as *"the current timestamp either in milliseconds
or microseconds"*, so GLOBIN supports both and assumes neither globally.

**All arithmetic is integer microseconds.** Not floats — a binary float cannot hold
`6000.346` — and not `Decimal`, because an offset is a coordinate difference on an
exact integer grid rather than a magnitude whose rounding is a financial decision.
That distinction is [`TIME_POLICY.md`](../TIME_POLICY.md)'s, and
[`PRECISION_POLICY.md`](../PRECISION_POLICY.md) owns the other half of it.

There is **one** flooring step in the whole path, and it happens last:

```text
corrected_micros = moment.epoch_micros + offset_micros
microseconds  → corrected_micros
milliseconds  → corrected_micros // 1000
```

Correcting a value that had already been floored would discard the sub-millisecond
part and then add a correction derived from it. Flooring towards the past is
`TIME_POLICY.md`'s existing rule, and here it is load-bearing rather than merely
consistent — see [the venue's rule](#the-venues-rule) below.

`recvWindow` is milliseconds only, is a `Decimal` read from configuration as
**text**, and renders positionally with its scale preserved. Phase 035 established
that; nothing here changes it.

---

## The venue's rule

Quoted verbatim from `rest-api.md`, section *Timing security*:

```javascript
serverTime = getCurrentTime()
if (timestamp < (serverTime + 1 second) && (serverTime - timestamp) <= recvWindow) {
  // begin processing request
  serverTime = getCurrentTime()
  if (serverTime - timestamp) <= recvWindow {
    // forward request to Matching Engine
  } else {
    // reject request
  }
  // finish processing request
} else {
  // reject request
}
```

**The window is evaluated twice, and the second evaluation carries no `+ 1 second`
clause.** That asymmetry shapes every threshold below:

- the **future** allowance is admission-time only. Nothing protects a timestamp
  that is ahead of the venue at the second check;
- the **past** half must survive the venue's own internal queueing — a delay that
  happens after GLOBIN's request has arrived and that GLOBIN therefore cannot
  measure at all.

### Which side each risk lands on

This is the easy thing to get backwards, so it is written down.

**Network delay pushes a timestamp into the venue's past, never its future.** While
a request is in flight the venue's clock advances, so transit time is spent against
`recvWindow` and never against the future allowance.

It follows that the only thing that can put a GLOBIN timestamp *ahead* of the venue
is the estimate being wrong — which is exactly `uncertainty`. Bounding
`max_uncertainty` below 1000 ms at **construction** therefore makes the future half
of the venue's check structural, and there is deliberately **no future-side runtime
gate**: it could never fire, and this repository does not write a threshold that
cannot fire.

---

## The five states

| State | Reached when | Admits a signature |
|---|---|:---:|
| `uninitialized` | no calibration has ever succeeded | no |
| `synchronized` | fresh sample, inside every bound | **yes** |
| `stale` | the sample is older than the freshness interval | no |
| `degraded` | the last probe failed, a recent sample survives | no |
| `unsynchronized` | a wall-clock jump, an offset leap, or a venue `-1021` | no |

Exactly one admits, and `tests/contract/test_clock_sync_contract.py` asserts the *count*
rather than the name — so a sixth state cannot quietly become a second admitting
one.

Three of the four refusals are kept apart because the remedies differ. `stale` says
*ask again*; `degraded` says *the venue stopped answering and here is what it last
said*; `unsynchronized` says *we were told we are wrong*. Collapsing them would send
three different problems to the same place.

**Nothing persists an offset.** A `ClockManager` starts with every domain
`uninitialized`, reads no file and restores nothing, so a fresh process signs
nothing until it has asked. That is the answer to *do not trust an old in-memory
offset after a restart*: there is no old offset to trust.

---

## Wall-clock jump detection

Both host clocks measure the same span, and the monotonic one is documented as *not
affected by system clock updates*. So any disagreement between the two intervals is
the wall clock being moved:

```text
divergence = (wall_after - wall_before) - (monotonic_after - monotonic_before)
```

Beyond `max_wall_divergence` the domain becomes `unsynchronized`, and a fresh
calibration is required. The threshold is not zero because the two clocks are read
at slightly different instants.

**The check runs at status time, not at calibration time**, and that is the point of
it. A wall clock adjusted *between* a calibration and a request is exactly the case
a calibration-time check would miss — and it is the common one, because a time
service corrects the host while GLOBIN sits idle.

The wall difference is computed as an epoch subtraction rather than through a
`Duration`, because `Duration` refuses a negative count and a clock set **backwards**
produces exactly that. `TIME_POLICY.md` already names this as the case where an
explicit epoch subtraction is the right tool.

---

## `recvWindow` and why it is never widened

The window is decided once, at admission, against the measured uncertainty. There
is **no adaptive branch**, and its absence is a deliverable rather than an omission.

The tempting behaviour — notice the clock is uncertain, raise `recvWindow` to
compensate — is precisely the behaviour that converts a clock fault into an accepted
stale request. It is also useless: the venue re-checks the window immediately before
the Matching Engine, so a wider window buys no protection against the queueing delay
GLOBIN cannot see.

When the window does not cover the required allowance, GLOBIN **refuses**. Two
refusals, because two different things can be wrong:

| Outcome | Meaning | Remedy |
|---|---|---|
| `recv_window_policy_violation` | the configured window is narrower than the allowance | widen it, up to the venue's ceiling |
| `timing_budget_exceeded` | no window the venue accepts could cover the allowance | fix the network or the clock; widening cannot help |

The venue's 60000 ms ceiling is not enforced by the policy, because it cannot be
reached there: `RecvWindow` refuses anything larger at construction, so a policy
holding an over-large window cannot exist.

---

## The admission gate

Seven gates, cheapest and broadest first, so the message an operator reads names the
outermost thing that is wrong.

| # | Gate | Refusal |
|:-:|---|---|
| 1 | a server-time source is declared for this domain | `clock_source_unavailable` |
| 2 | a calibration has succeeded | `clock_not_synchronized` |
| 3 | the estimate has not been disbelieved | `clock_jump_detected` |
| 4 | it is fresh | `clock_calibration_stale` |
| 5 | its error bound is inside the limit | `clock_uncertainty_exceeded` |
| 6 | the round trip is inside the limit | `clock_uncertainty_exceeded` |
| 7 | the window covers uncertainty plus network budget | `recv_window_policy_violation` / `timing_budget_exceeded` |

**A refusal carries no timing context.** A caller that ignored the outcome would, on
any other design, find a plausible timestamp to use. Here there is nothing to read —
the same property `EndpointResolution` has for a refused endpoint.

**A `TimingContext` is produced only by a passing admission**, and
`sign_request` takes one instead of a clock. So "one timing context per signature
operation" is a property of the object graph rather than a rule: there is no object
in scope during canonicalisation that could produce a second timestamp.

---

## `-1021` recovery

`-1021 INVALID_TIMESTAMP` is documented with two meanings, both quoted from
`errors.md`:

> Timestamp for this request is outside of the recvWindow.
> Timestamp for this request was 1000ms ahead of the server's time.

Both are refusals at the timing gate, before the Matching Engine, so
[`rest-transport.toml`](rest-transport.toml) declares the code **unambiguous** — the
same reading that keeps 403, 418 and 429 out of the ambiguous status table. Marking
it ambiguous would be unsafe rather than cautious: it would make the one timing
failure that is always safe to re-send permanently unretryable.

The flow:

1. the venue answers `-1021`;
2. the domain is invalidated — `unsynchronized`, whatever the window holds;
3. a fresh calibration is required before anything else;
4. the admission gate runs again against the new estimate;
5. **at most one** re-send, and only when it is provably safe.

| Condition | Verdict |
|---|---|
| a code other than `-1021` | `no_action` |
| the outcome is not a **confirmed** failure | `resync_only` |
| already re-sent once | `resync_only` |
| a read-only request, or one declared idempotent | `resync_and_retry_once` |
| a mutating request with no idempotency declaration | `resync_only` |

Two rules in that table are load-bearing. **An unknown outcome is never replayed** —
[ADR-0089](../adr/0089-an-unknown-outcome-is-preserved-and-a-second-module-may-reach-a-socket.md)'s
rule does not acquire an exception because the remedy happens to be obvious. And
**silence is not a declaration**: a caller that has not said a re-send is safe has
not said it is safe.

`max_retries = 1` is not configurable. A retry budget an operator can raise is a
retry engine, and Phase 043 owns those. Phase 036 decides; it does not act.

---

## Concurrency

`ClockManager` holds one calibration window per domain behind one lock, with
**single-flight per domain**: the first caller to find a domain stale performs the
exchange, and every other caller waits on that flight and reads its result.

Four properties, each a consequence of the structure rather than a case that is
handled:

- **one exchange, not one per caller.** Ten threads finding a domain stale produce
  one probe;
- **different domains never block each other**, because the lock is held only for
  the small bookkeeping and never across the exchange;
- **deadlock is impossible**, for the same reason: no code path holds the lock
  while calling anything that could block;
- **a waiter that gives up changes nothing.** It records a failure for itself and
  returns; the leader's result still lands, and the shared window is exactly what
  it would have been.

A leader that raises still releases every waiter, because `done` is set in a
`finally`.

`waiting_on(domain)` reports how many callers a slow venue is currently holding. It
is a diagnostic; nothing branches on it.

---

## Configuration

Nine settings under `clock`, documented in
[`CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md) and defaulted in
[`clock-contract.toml`](clock-contract.toml).

**A set of thresholds that contradicts itself cannot be constructed.** Three of the
checks are not about one field at all:

- a degraded grace shorter than the freshness interval makes `degraded` unreachable;
- a `max_uncertainty` above half of `max_round_trip` makes the uncertainty gate
  unreachable, because uncertainty *is* half the round trip;
- a `max_uncertainty` at or above 1000 ms describes a host whose admitted timestamps
  could land beyond the venue's own future tolerance.

The refusal happens at `config.valid`, so an operator's mistake is exit code `14` at
the gate rather than a surprise at the first request.

`clock.require_calibration` defaults to `true`, and **turning it off does not permit
signing against an unsynchronised clock** — nothing consults it in the admission
gate, which refuses on the state alone. It exists so an operator can say *this host
is not expected to reach a venue*, and so a diagnostic can report that intent rather
than an absence.

---

## Diagnostics

Every published dimension has a value set that can be counted when it is written,
which is what [`TELEMETRY_POLICY.md`](../TELEMETRY_POLICY.md) requires.

| Published | Cardinality |
|---|---|
| clock domain, environment, product, protocol | one per declared registry row |
| synchronization state | 5 |
| round-trip bucket | 9 |
| calibration-age bucket | 9 |
| offset-magnitude bucket, with sign | 14 |
| admission refusal reason | 8 |
| recovery verdict | 3 |

**Deliberately not published:** the timestamp itself, the exact offset in
microseconds, the round trip in nanoseconds, any request identifier, any symbol, any
query string. None of them is secret — a clock offset protects nothing — and every
one of them is unbounded in cardinality. The signed offset in **whole milliseconds**
is published beside its bucket, because an operator diagnosing a clock needs the
number and a dashboard does not.

There is no credential anywhere in this layer, no secret store read and no signature
produced, so there is nothing here to redact. That is structural rather than
remembered.

---

## Verifying clock health

```bash
globin clock domains
```

Every declared domain and whether it can be calibrated at all. Opens nothing.

```bash
globin clock status --json
```

What GLOBIN believes about each clock, and the policy in force. Opens nothing, so
a fresh invocation reports every domain `uninitialized` and exits `3` — nothing has
been established, which is not the same as something being wrong.

```bash
globin clock calibrate --family spot --environment testnet
```

Fills the window: one public, read-only, credential-free server-time exchange per
configured sample. **Reaches the venue.** Prints what it is about to do before
opening a connection, sets no host clock and writes no file.

**It takes `sample_count` exchanges rather than one**, and that is not merely
thorough. A window of one gives the fastest-sample rule nothing to choose between,
and the first exchange on a fresh pool is the one that pays the handshake. Measured
against the venue's testnet from the declared host, that first sample estimated the
offset about 100 ms further out than the four that followed — see
[`phase_036_sources.md`](../research/phase_036_sources.md) M-01. Every exchange is
reported, failures included, so *four of five timed out* is visible rather than
hidden behind the one that answered.

```bash
globin clock selftest
```

Eight checks, offline. One of them runs the venue's own published pseudo-code
against a timestamp GLOBIN admitted, at both extremes of the error bound GLOBIN
claimed.

```bash
globin clock evidence
```

Writes `.globin/clock/clock-manifest.json`.

Exit codes reuse the health triad every gate here already speaks — `0` synchronized,
`3` nothing established, `1` unsynchronized or a failed check. **No twenty-sixth
exit code was added; 26 stays free.**

---

## What this phase did not do

- **No host clock is set.** GLOBIN measures the difference and applies it to its own
  timestamps. Correcting the machine is an operator's job and an elevated one.
- **No offset is persisted.** Recovery from a restart is re-calibration.
- **No retry is executed.** `-1021` produces a *verdict*; Phase 043 owns the
  executor.
- **No rate-limit accounting.** The probe's weight is recorded in
  `rest-transport.toml` and consulted by nothing. Phases 041 and 042.
- **No WebSocket or FIX clock source.** The port is protocol-agnostic and the
  WebSocket `time` method is documented; no WS engine exists to drive it.
- **No startup calibration gate.** `globin bootstrap check` reaches no network — a
  property tested since Phase 021 — so calibration is enforced at *signing*, not at
  *start*. That is Phase 035's argument for `required_credentials()` staying empty,
  applied to the same boundary.

---

## Related documents

| Question | Document |
|---|---|
| Which types express time, and where may a clock be read? | [`TIME_POLICY.md`](../TIME_POLICY.md) |
| Why is the offset taken from the fastest sample? | [ADR-0093](../adr/0093-server-time-is-estimated-from-the-lowest-round-trip-and-a-window-is-never-widened.md) |
| Why did Phase 036 deliver this rather than its own title? | [ADR-0092](../adr/0092-phase-036-widens-to-deliver-the-clock-discipline-layer.md) |
| What signs a request, and with what? | [`REST_AUTHENTICATION.md`](REST_AUTHENTICATION.md) |
| How is a request sent, and what is an unknown outcome? | [`REST_TRANSPORT.md`](REST_TRANSPORT.md) |
| Which endpoints exist, and for which environments? | [`BINANCE_API_REALITY.md`](BINANCE_API_REALITY.md) |
| What may an operator configure? | [`CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md) |
| Where did these facts come from? | [`research/phase_036_sources.md`](../research/phase_036_sources.md) |
