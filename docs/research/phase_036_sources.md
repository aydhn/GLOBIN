# Phase 036 — Source Ledger

Every external fact the clock discipline layer encodes, where it was read, and what
it changed about the implementation.

**Four entries, and only one of them is a new source.** That is the phase's most
useful property rather than a thin ledger: almost everything the clock layer needs —
`GET /api/v3/time`, the `serverTime` field, the `recvWindow` bounds, the two
timestamp units and the processing rule itself — was already recorded with
provenance by Phases 033 to 035. Phase 036 consumes what those phases wrote down and
adds exactly one document to the registry.

**That one document repaid the visit twice.** It was read for `-1021`, and reading it
also found a code Phase 034 had misclassified. See S-01.

Every document below was fetched raw and grepped locally. Nothing here was read
through a summarising intermediary.

---

## Drift check against Phases 033, 034 and 035

Three of the documents this phase depends on were already recorded in
[`binance-api-reality.toml`](../engineering/binance-api-reality.toml). Their digests
were recomputed on access and compared:

| Source | Recorded digest | On access |
|---|---|---|
| `spot-rest` | `sha256:49ea6809…427999` | **unchanged** |
| `spot-changelog` | `sha256:e6da6a7b…ef7681` | **unchanged** |
| `spot-ws-api` | `sha256:c09a1f5c…09a8d` | **unchanged** |

No source this phase depends on has moved since it was last read, so the registry
required no drift acknowledgement and none was written.

---

### S-01 — Binance Spot error codes

**Canonical location:** https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/errors.md

**Accessed:** 2026-08-20

**Authority:** Tier 1 — primary. Newly declared as `spot-errors`.

**Digest at access:** `sha256:5e3a9a7bda255e0177f2928bcb68ea09cf5b73a45186756d008bdf7afc3f10f9`

**What it establishes**, quoted in full for the two codes that matter:

> ### -1021 INVALID_TIMESTAMP
>  * Timestamp for this request is outside of the recvWindow.
>  * Timestamp for this request was 1000ms ahead of the server's time.

> ### -1006 UNEXPECTED_RESP
>  * An unexpected response was received from the message bus. Execution status unknown.

**Implication for GLOBIN — two of them, and the second was not what this phase came for.**

`-1021` carries **two** documented meanings, and the second is the future-side bound
stated from the venue's own side — the same 1000 ms the `Timing security` pseudo-code
expresses as `+ 1 second`. Both are refusals at the timing gate, before the Matching
Engine, so `rest-transport.toml` declares the code **unambiguous**. That is what makes
the bounded one-shot recovery reachable rather than universal: `globin.domain.clock_sync`
permits a re-send only on a *confirmed* failure, and an ambiguous `-1021` would have
made the one timing failure that is always safe to re-send permanently unretryable —
the same argument Phase 034 already made for keeping 403, 418 and 429 out of the
ambiguous status table.

**The brief attributed `-1021` to the Futures error contract.** It is documented on
**Spot**, in this file, with both meanings. The correction cost nothing and is
recorded because the plan said otherwise.

**`-1006` is a defect this phase repaired rather than delivered.** Phase 034 declared
`-1007` as ambiguous, quoted from `rest-api.md`, which mentions that one code inline.
The full table lives here, and no phase had read it. `-1006`'s own documented text
ends *"Execution status unknown"* — the venue describing
[ADR-0089](../adr/0089-an-unknown-outcome-is-preserved-and-a-second-module-may-reach-a-socket.md)'s
`UNKNOWN` in its own words — and GLOBIN was classifying it as a confirmed failure.
A mutating request answered `-1006` would have been recorded as *did not happen* when
the venue had said the opposite. The row is added in this phase's diff.

---

### S-02 — Binance Spot REST API, Timing security

**Canonical location:** https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/rest-api.md
— section *Timing security*

**Accessed:** 2026-08-20

**Authority:** Tier 1 — primary. Already declared as `spot-rest`.

**Digest at access:** `sha256:49ea6809243fc7fb426e07f2fe662097736c7bb405bd2da5eef637d715427999` — **unchanged** since Phase 033.

**What it establishes.** The processing rule, quoted verbatim and in full, because
the part that matters is the part Phase 035 did not need:

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

Also quoted:

> **Serious trading is about timing.** Networks can be unstable and unreliable,
> which can lead to requests taking varying amounts of time to reach the servers.

**Implication for GLOBIN, and it is the central finding of the phase.** The window is
evaluated **twice**, and the second evaluation — immediately before the request
reaches the Matching Engine — carries **no `+ 1 second` clause**. Phase 035 recorded
the rule and took from it only the reason the ceiling matters; reading it again for
an implementation makes the asymmetry load-bearing:

- the **future** allowance is admission-time only. Nothing protects a timestamp that
  is ahead of the venue at the second check;
- the **past** half must survive the venue's own internal queueing, which happens
  after GLOBIN's request has arrived and which GLOBIN cannot measure.

That is why `admit()` spends the network budget against `recvWindow` and never
against the future tolerance, and why the phase refuses rather than widening. It is
also why there is **no future-side runtime gate**: transit advances the venue's clock
while a request is in flight, so the only thing that can put a timestamp ahead of the
venue is the estimate being wrong — which `ClockDiscipline` bounds at construction.

**Getting that direction backwards is the easy mistake, and this phase made it
first.** The plan's own gate list had the network budget on the future side. The
arithmetic caught it: the default thresholds then failed their own construction
check, because 250 ms of uncertainty plus a 1000 ms budget reaches the 1000 ms
tolerance. The rule that refused them was written before the defaults it refused.

---

### S-03 — Binance Spot REST API, Check server time

**Canonical location:** https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/rest-api.md
— section *Check server time*

**Accessed:** 2026-08-20

**Authority:** Tier 1 — primary. Already declared as `spot-rest`.

**What it establishes**, quoted in full:

> ```
> GET /api/v3/time
> ```
> Test connectivity to the Rest API and get the current server time.
>
> **Weight:** 1
> **Parameters:** NONE
> **Data Source:** Memory
> **Response:**
> ```javascript
> {
>     "serverTime": 1499827319559
> }
> ```

**Implication for GLOBIN.** Nothing new was written for this. Phase 034 had already
recorded the endpoint as the `spot.time` probe in
[`rest-transport.toml`](../engineering/rest-transport.toml), with its weight, its
method and its path relative to the registry's `path_prefix`. Phase 036 reads that
declaration and adds no second copy — which is why
`globin clock calibrate --family usds_m_futures` refuses rather than guessing: the
contract declares no `usds_m_futures.time` probe, and a path is never invented.

*Parameters: NONE* is what makes the probe credential-free and side-effect-free.
*Data Source: Memory* is why its round trip is a network measurement rather than a
measurement of the venue's database.

---

### S-04 — Binance Spot WebSocket API, `time`

**Canonical location:** https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/web-socket-api.md
— section *Check server time*

**Accessed:** 2026-08-20

**Authority:** Tier 1 — primary. Already declared as `spot-ws-api`.

**Digest at access:** `sha256:c09a1f5c7ebfd111fed79f07e98c3cf0d862d0f3c8d6636b57bd2dac83d09a8d` — **unchanged** since Phase 033.

**What it establishes**, quoted:

> ```javascript
> {
>     "id": "187d3cb2-942d-484c-8271-4e2141bbadb1",
>     "method": "time"
> }
> ```
> Test connectivity to the WebSocket API and get the current server time.
>
> **Weight:** 1
> **Parameters:** NONE

**Implication for GLOBIN.** The same fact is published over a second surface with the
same field name, which is why `ServerTimeSource` is a **protocol-agnostic port** with
one method rather than an HTTP-shaped one. The WebSocket clock domain is expressible
today and refuses today, because no WebSocket engine exists to drive it — building
one for this phase would be the premature implementation `CLAUDE.md` calls a defect.

The port therefore costs nothing now and buys one thing later: a second
implementation arrives with no caller changing.

---

### M-01 — the handshake bias, measured against the venue rather than argued

**Not a document.** A measurement taken from the declared host against
`testnet.binance.vision` on 2026-08-20, with `globin clock calibrate --family spot
--environment testnet`.

ADR-0093 argues that the first exchange on a fresh connection pool pays a TCP and
TLS handshake, that its elapsed time is therefore not a round trip, and that an
averaging estimator would fold that into the offset. That argument was made from
the transport's design. This is what it looks like in practice:

| Exchange | Round trip | Estimated offset |
|---:|---:|---:|
| 1 | 483 ms | **+122 ms** |
| 2 | 281 ms | +20 ms |
| 3 | 287 ms | +15 ms |
| 4 | 277 ms | +21 ms |
| 5 | 277 ms | +20 ms |

**The first sample's estimate is about 100 ms wrong**, and the four that follow
agree with each other to within 6 ms. A mean over all five would have reported
roughly +40 ms — twice the converged value, and wrong in a direction that would
persist for as long as the window held that sample. The minimum-round-trip rule
selected exchange 4 or 5 and reported **+20 ms**.

**Implication for GLOBIN, and it changed the command rather than the estimator.**
The estimator was already right. What was wrong was `globin clock calibrate`, which
took **one** sample — so the fastest-sample rule had nothing to choose between, and
a first exchange that exceeded the transport's timeout outright made the whole
command report *no usable reading*. That is what a single-sample calibration does
on a link whose first handshake is slow, and it was found by running the command
against the venue rather than by any offline test. `ClockManager.calibrate_window`
now fills the window, and every exchange is reported so that four failures among
five are visible rather than hidden behind one succeeding estimate.

---

## What was looked for and not found

**A documented server-time endpoint for USDⓈ-M Futures, COIN-M Futures or Options.**
The brief names `/fapi/v1/time`, `/dapi/v1/time` and `/eapi/v1/time`. None is
recorded in this repository and none was added, for the reason Phase 034 recorded
and this phase re-confirmed: the derivatives documentation lives at
`developers.binance.com/docs`, which is client-rendered and is declared
`regime = "manual"` in the registry. [`SOURCE_POLICY.md`](../SOURCE_POLICY.md)
forbids both scraping it and accepting a generated summary in its place.

So those three paths are spelled **nowhere** in this package. The clock domains are
named and modelled; asking any of them for the time refuses with the registry's own
recorded status. That is the brief's own rule — *do not invent an endpoint* — and its
own test 30, and it is a measurement rather than a gap: the day a row is added to the
registry, the domain becomes calibratable with no change to the clock layer.

**A documented figure for the venue's internal queueing delay.** The pseudo-code
shows that the window is re-checked before the Matching Engine, and no document
bounds how long that takes. GLOBIN therefore *assumes* a network budget rather than
reading one, and [`clock-contract.toml`](../engineering/clock-contract.toml) says so
in the comment above the default. An assumption declared as an assumption is the
honest form; a number presented as a venue fact would not be.

---

## Related documents

| Question | Document |
|---|---|
| What was decided about clocks? | [ADR-0093](../adr/0093-server-time-is-estimated-from-the-lowest-round-trip-and-a-window-is-never-widened.md) |
| Why did Phase 036 deliver this? | [ADR-0092](../adr/0092-phase-036-widens-to-deliver-the-clock-discipline-layer.md) |
| How does the layer work? | [`CLOCK_DISCIPLINE.md`](../engineering/CLOCK_DISCIPLINE.md) |
| What may be cited, and how? | [`SOURCE_POLICY.md`](../SOURCE_POLICY.md) |
| Where do these sources live? | [`binance-api-reality.toml`](../engineering/binance-api-reality.toml) |
| What did Phase 035 record about timing? | [`phase_035_sources.md`](phase_035_sources.md) |
