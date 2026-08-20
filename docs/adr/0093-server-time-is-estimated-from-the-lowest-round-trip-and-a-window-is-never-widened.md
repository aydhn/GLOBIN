# ADR-0093 — Server time is estimated from the lowest round trip, and a window is never widened to fix a clock

## Status

Accepted — Phase 036.

**Date:** 2026-08-20

## Context

GLOBIN must send Binance a `timestamp` the venue will accept. The venue evaluates
it against its own clock, and publishes the rule as pseudo-code
([`phase_036_sources.md`](../research/phase_036_sources.md) S-02):

```javascript
serverTime = getCurrentTime()
if (timestamp < (serverTime + 1 second) && (serverTime - timestamp) <= recvWindow) {
  serverTime = getCurrentTime()
  if (serverTime - timestamp) <= recvWindow {
    // forward request to Matching Engine
```

Three facts about that rule force the decisions below.

**The window is evaluated twice, and the second evaluation has no future
tolerance.** So the `+ 1 second` allowance protects only admission, while the past
half of the window must additionally survive the venue's own internal queueing —
an interval that occurs after GLOBIN's request has arrived and that GLOBIN cannot
measure at all.

**The host clock is not a usable input on its own.** `time.get_clock_info('time')`
reports `adjustable=True` on the declared host, and the Windows Time Service, an
NTP step and an operator all move it silently.

**Any estimate of the venue's clock has an error, and the error is bounded by the
round trip.** GLOBIN sends a request, the venue stamps its answer at some unknown
moment, and the answer comes back. Nothing observable narrows that moment further
than the interval it happened in.

## Decision

**The offset is estimated by the NTP midpoint over a single exchange**, anchored
once on the wall clock and extended along a monotonic span:

```text
round_trip     = monotonic_finished - monotonic_started
local_midpoint = wall_anchor + round_trip / 2
offset         = serverTime - local_midpoint
uncertainty    = round_trip / 2
```

**The chosen sample is the one with the lowest round trip in a bounded window**, the
later sample winning a tie. Not an average, not a median.

**The uncertainty is carried, never discarded.** Every gate downstream is expressed
in terms of it, and it is what a diagnostic publishes beside the offset.

**All arithmetic is integer microseconds, with exactly one flooring step**, applied
after the correction rather than before it.

**GLOBIN never widens `recvWindow` to compensate for clock uncertainty.** When the
configured window does not cover the uncertainty plus the network budget, admission
is **refused**. There is no adaptive branch, and its absence is declared as a
prohibition in [`clock-contract.toml`](../engineering/clock-contract.toml).

**A `TimingContext` is constructible only by a passing admission**, and
`sign_request` takes one in place of a clock.

**The future half of the venue's check is enforced at construction rather than at
admission.** `ClockDiscipline` refuses a `max_uncertainty` at or above 1000 ms, so
no admitted sample can breach the `+ 1 second` allowance and no runtime gate for it
exists.

## Consequences

**A host with a slow or asymmetric link signs nothing.** That is the intended cost.
An operator on a 3-second link gets a refusal naming the round trip rather than a
request the venue rejects.

**A refusal names one of two remedies rather than one.** `recv_window_policy_violation`
means *widen the configured window, up to the ceiling*; `timing_budget_exceeded`
means *no window the venue accepts could cover this, so fix the network or the
clock*. Collapsing them would tell half of the operators to do something that cannot
work.

**`sign_request`'s signature changed**, which breaks any Phase 035 caller. There is
one, in the command surface, and the Phase 035 test suite was updated to build a
context rather than pass a moment — with a zero offset, so every published signature
vector still reproduces byte for byte.

**The venue's `X-MBX-TIME-UNIT: MICROSECOND` header is not sent**, and that is a
measurement rather than an omission. It would remove a half-millisecond quantisation
from an estimate whose stated uncertainty is tens of milliseconds on any real link.
The unit that *arrived* is recorded on every sample, so a future change is visible.

**Nothing persists an offset**, so a restart re-calibrates. The cost is one exchange
at start-up; the benefit is that there is no stored value a restart could trust
without re-measuring.

**Enforcement is a contract test rather than a convention.**
`tests/contract/test_clock_sync_contract.py` recomputes the declared defaults into a
discipline and compares it against the code's, executes the declared estimator name
against a window whose fastest sample is known, and asserts the prohibition table
against the source — including that no spelling of `SetSystemTime` appears anywhere
in the package.

## Alternatives Considered

**`offset = serverTime - now_at_receive`, the naive estimator.** Rejected on
arithmetic. It attributes the entire round trip to the offset, so a host with a
perfect clock on a 200 ms link measures itself 200 ms fast and corrects itself into
being 200 ms wrong. A unit test asserts exactly that counterfactual.

**An average, or a median, over the sample window.** Rejected for two reasons,
and the second was subsequently **measured** rather than left as reasoning — see
[`phase_036_sources.md`](../research/phase_036_sources.md) M-01, where the first
exchange against the venue's testnet estimated the offset about 100 ms further out
than the four that followed it.
The bound: a midpoint estimate is wrong by at most half *its own* round trip, so the
fastest sample is by definition the tightest estimate available and no combination of
samples is tighter. And the transport: `HttpRestTransport` pools connections, so the
first exchange on a fresh pool pays a TCP and TLS handshake and its elapsed time is
not a round trip at all — an averaging estimator folds that handshake into the
offset, while selecting the minimum discards it without needing to know which sample
was first. A median over a low-round-trip subset costs a sort and a tie rule and
improves no bound.

**Widening `recvWindow` when the clock looks uncertain.** Rejected as unsafe rather
than merely inelegant. It converts a clock fault into an accepted stale request, and
it does not even work: the venue re-checks the window immediately before the Matching
Engine, so a wider window buys no protection against the queueing delay GLOBIN cannot
see. [`auth_timing.py`](../../src/globin/domain/auth_timing.py) has carried the
sentence *"a wider window is not the remedy for a clock that disagrees with the
venue"* since Phase 035; this is where it became executable.

**Correcting the host clock instead of correcting GLOBIN's timestamps.** Rejected on
scope and on privilege. Setting a Windows clock needs elevation, affects every other
process on the machine, and would make GLOBIN responsible for a resource it does not
own. `MEMORY.md` records that this deployment is multi-machine and multi-account.

**A runtime gate for the venue's future tolerance.** Rejected because it could never
fire. Network delay advances the venue's clock while the request is in flight, so
transit is spent against `recvWindow` and never against the future allowance; the
only thing that can put a timestamp ahead of the venue is the estimate being wrong,
which the construction-time bound on `max_uncertainty` already prevents. This
repository does not write a threshold that cannot fire.

**Keeping `moment: Instant` on `sign_request` and adding the timing context beside
it.** Rejected because it would leave two sources of a timestamp in one function and
make "one timing context per signature operation" a rule somebody keeps rather than a
property of the object graph.

## Risks and Trade-offs

**The characteristic failure mode is a persistently asymmetric path.** The midpoint
assumes the outbound and return legs are equal. On a route where they are reliably
not — a satellite hop, an asymmetric proxy — the offset is wrong by up to half the
round trip in a *consistent direction*, and taking more samples does not help because
every sample is wrong the same way. The stated uncertainty still bounds the error, so
GLOBIN is not lying about its confidence; it is simply less accurate than it could be
with a better estimator.

**The observable signal is `-1021` from a host whose `clock status` reports
`synchronized`.** That combination is the one this design cannot explain any other
way, and it is why the `-1021` recovery invalidates the domain rather than merely
retrying.

**A second risk is that the thresholds are chosen rather than measured.** The
freshness interval is derived from a 20 ppm oscillator specification and the network
budget is an assumption about a delay nobody outside Binance can observe. Both are
reasoned in [`clock-contract.toml`](../engineering/clock-contract.toml) and both are
configurable. The signal that one is wrong is a domain that oscillates between
`synchronized` and `degraded` without the link changing.

**Confidence in the estimator itself is high**; confidence in the specific numbers is
moderate, and this record says so rather than implying otherwise.

## References

- [`CLOCK_DISCIPLINE.md`](../engineering/CLOCK_DISCIPLINE.md) — the delivered layer.
- [`clock-contract.toml`](../engineering/clock-contract.toml) — the declared half.
- [`phase_036_sources.md`](../research/phase_036_sources.md) — the venue's own words.
- [ADR-0089](0089-an-unknown-outcome-is-preserved-and-a-second-module-may-reach-a-socket.md) —
  the rule the `-1021` recovery inherits rather than excepts.
- [ADR-0091](0091-authentication-is-capability-driven-and-product-scoped.md) — no
  product's contract stands in for another's, which is why a clock domain carries a
  product.
- [ADR-0035](0035-milliseconds-are-a-floored-projection.md) — why the one flooring
  step floors towards the past.
- [`TIME_POLICY.md`](../TIME_POLICY.md) — the wall/monotonic split this rests on.

## Supersedes

None.

## Superseded By

None.
