# ADR-0088 — Phase 034 widens to deliver the REST transport substrate

## Status

Accepted — Phase 034. **Date:** 2026-08-19

## Context

`ROADMAP.md` row 034 reads *Official Documentation Ingestion and Change Tracking*,
with the purpose *"Establish a repeatable process for consuming official Binance
documentation and detecting changes to it."*

This phase's brief asked for something else entirely: a deterministic, typed,
fail-closed multi-product REST transport substrate — endpoint resolution driven by
Phase 033's registry, canonical URL and query encoding, connection lifecycle, JSON
and SBE content negotiation, HTTP and venue outcome semantics, diagnostics with
redaction, public connectivity probes, and machine-readable evidence.

That is row **045**, *REST Transport Layer*, eleven rows ahead. And it is not only
row 045: the brief additionally names work owned by five other rows in this band.

| Row | Title | What of the brief it owns |
|---|---|---|
| 035 | Environment Classification Model | Production, demo and testnet as classes with distinct guarantees |
| 036 | Product and Environment Capability Matrix | Which product supports which environment, driven by evidence |
| 037 | Base URL and Endpoint Registry | Endpoint definitions per product and environment, no hard-coded literals |
| 041 | Rate Limit Weight Registry | The documented weight of a request |
| 043 | Retry, Backoff and Idempotency Policy | Which failures are retryable, and idempotency classification |
| 044 | Error Code Mapping and Classification | Venue error codes mapped with retryable and fatal classification |
| 045 | REST Transport Layer | The REST client with timeouts, connection reuse and instrumentation |
| 047 | FIX and SBE Interface Assessment | Whether the documented SBE interface provides material value |

**The audit found the transport subject entirely empty**, and one half of row 034's
subject already built. Nothing under `src/globin` opened an outbound connection;
`errors.py` had carried `TransportError` and `ExchangeError` since Phase 005, both
with the note *"Phases 033-048 introduce the callers"*, and neither had one.
Meanwhile [`scope-amendments.toml`](../engineering/scope-amendments.toml) recorded
Phase 034 as already inheriting *"an allowlisted refresh over official
machine-readable sources, source digests, and a deterministic classified diff"*,
with only three things absent by design: **no cadence, no accumulated change log
across runs, no review workflow for a breaking drift.**

The operator was shown the conflict and the options before any code was written,
and chose to deliver both halves.

### Why the two halves are one phase rather than two

This is the condition that makes the amendment defensible rather than convenient,
so it is stated precisely.

The brief's own fail-closed rule lists the states a REST resolution must refuse:
`unsupported`, `unknown`, **`stale`**, `conflicted`. Nothing in this repository
could answer whether a source was stale. Phase 033 recorded *when* each official
document was read and **nothing consumed the date** — a registry read once and
never again looked exactly like one re-checked yesterday.

So the transport half cannot enforce its own security rule without the ingestion
half. The cadence is not adjacent work that happened to fit; it is gate 9 of ten in
`resolve()`, and without it that gate does not exist.

## Decision

**Phase 034 delivers both subjects**, as the eighteenth scope amendment.

1. **The REST transport substrate**, per the brief:
   `globin.domain.rest` (typed contracts, canonical encoding, outcome
   classification), `globin.domain.rest_endpoint` (capability-gated resolution),
   `globin.domain.rest_contract`, `globin.ports.rest`,
   `globin.adapters.rest_transport` (the one outbound module),
   `globin.adapters.rest`, `globin.application.rest`, and a `rest` command group.
   The engineering record is
   [`REST_TRANSPORT.md`](../engineering/REST_TRANSPORT.md); the technical decisions
   inside it are
   [ADR-0089](0089-an-unknown-outcome-is-preserved-and-a-second-module-may-reach-a-socket.md).

2. **Row 034's own remaining subject**: a declared re-check cadence per source
   regime, an append-only change journal accumulated across runs, and a
   breaking-drift acknowledgement ledger that fails in both directions. The record
   is [`DOCUMENTATION_INGESTION.md`](../engineering/DOCUMENTATION_INGESTION.md).

3. **The join**: a source past its cadence makes every endpoint resting on it
   unresolvable, before any socket opens.

**No endpoint fact is duplicated.** Phase 033's registry remains the single source
of every base URL, and
`tests/architecture/test_api_reality_discipline.py` continues to fail if a venue
host is spelled anywhere in the package.

**No exit code is added. 26 stays free.** A refused resolution is `14`, which
already means the ask cannot be satisfied; an absent document is `3`.

## Consequences

`ROADMAP.md` row 034 is marked Complete and its purpose restated to name both
halves. Its `[[inheritance]]` row is retired. Six rows are recorded as displaced —
035, 036, 037, 041, 044 and 045 — and eight gain inheritance rows naming what they
will find partly built and what is deliberately absent. Rows **043** and **047**
are in the second list and not the first: retry and the FIX/SBE assessment are both
entirely intact as subjects, and what they inherit is groundwork rather than
finished work.

Row **045** is the one materially reduced: what remains of it is adopting
`binance-common` — which
[`wheel-survey.toml`](../engineering/wheel-survey.toml) still records against that
phase — and whatever the SDK changes about a transport that already exists. Its
purpose is restated rather than the row removed, because a row that shipped early
and a row that never existed are different facts.

`src/globin` now opens outbound connections. That property held from Phase 001 to
Phase 033 and is gone; what replaces it is a *bounded* property — exactly two
modules may touch a socket, one per direction, named in both directions by
`tests/architecture/test_library_discipline.py`. See ADR-0089.

The amendment scores **two of four**, which is the same as the seventeenth:

| Condition | Verdict | Why |
|---|---|---|
| Nothing displaced | **FAILED** | Six rows lose work — 035, 036, 037, 041, 044, 045. The largest displacement in the programme so far |
| Nothing deferred | **MET** | Both halves ship; nothing planned for row 034 is pushed out |
| No phase owns the work | **FAILED** | Row 045 owns the REST transport layer *by title*, as do 044 and 047 for parts |
| The two halves need each other | **MET** | The transport's `stale` gate does not exist without the cadence |

Stating the score honestly is the point of the ledger. This amendment fails the
same two conditions the seventeenth failed, and fails *nothing displaced* against
twice as many rows.

## Alternatives Considered

**Deliver only row 034 as written, and defer the transport to row 045.** Rejected
by the operator after the conflict was surfaced. It is the option that respects the
roadmap exactly, and its cost is that Phase 033's registry — the largest artefact
in the band — would have gone eleven more phases with no consumer, which is how a
declared document quietly becomes wrong.

**Pivot row 034 entirely to the transport and drop the ingestion subject.** Rejected
because the subject would then have belonged to no row at all, and because the
`stale` gate would have had nothing behind it. The result would have been a
fail-closed rule with one state it could never enter.

**Deliver the transport contracts but no HTTP client**, leaving the socket to Phase
045. Considered seriously: it preserves the *"`src/globin` opens no outbound
connection"* property intact. Rejected because the phase's own acceptance criteria
require credential-free connectivity probes, and because a transport nothing has
ever driven against the real venue is a transport whose header names are a
transcription nobody has checked — which is precisely the class of error S-02 and
S-03 in [the source ledger](../research/phase_034_sources.md) turned out to be.

**Adopt `httpx` as a tenth runtime dependency.** Rejected. It would give the
four-way timeout split the brief describes, and Phase 045 plans to adopt
`binance-common`, which brings its own client — two HTTP stacks in one tree is
worse than one honest `TimeoutPolicy` that reports which of its bounds are actually
enforced.

**Pull `binance-common` forward from Phase 045.** Rejected because the brief asks
GLOBIN to own the transport substrate rather than wrap an SDK, and because adopting
a dependency to avoid writing 300 lines of standard library is the trade
[`DEPENDENCY_POLICY.md`](../DEPENDENCY_POLICY.md) exists to refuse.

## Risks and Trade-offs

**Eight rows will find their subject partly built, six of them displaced.** Mitigated the way the
programme already mitigates it: an `[[inheritance]]` row per phase naming both what
exists and what is deliberately absent, because a phase told only what exists
rebuilds the boundary and one told only what is missing rebuilds what is there.

**Row 045 is now a smaller phase than its title suggests.** Accepted and recorded
rather than hidden. Its remaining work is real — the SDK adoption its wheel-survey
row still owns — and a reader of the roadmap will see a purpose that says so.

**The repository can now reach the internet from its own package.** The mitigation
is structural rather than procedural: two named modules, one direction each, both
asserted in both directions, plus routes that were entirely unguarded before this
phase (`http.client`, `urllib.request`, `ssl`) now closed. ADR-0089 records that
the outbound half of that rule is *stronger* than what it replaced.

**A cadence that nobody honours is a policy that lies.** The `manual` regime is
given 90 days rather than an aspirational figure, and the document says plainly
that no REST endpoint rests on a manual source today, so the row gates nothing yet.

## References

- [`ROADMAP.md`](../../ROADMAP.md) — rows 034 through 047
- [`docs/engineering/scope-amendments.toml`](../engineering/scope-amendments.toml) — the eighteenth amendment
- [`docs/engineering/GRANULARITY_REVIEW.md`](../engineering/GRANULARITY_REVIEW.md) — the condition tally
- [`docs/research/phase_034_sources.md`](../research/phase_034_sources.md) — five sources, three of which changed the code
- [ADR-0021](0021-phase-005-widens-to-include-the-test-foundation.md) — the four-part test being scored
- [ADR-0086](0086-phase-033-widens-to-deliver-the-binance-api-reality-registry.md) — the seventeenth amendment, which displaced rows 034-037
- [ADR-0089](0089-an-unknown-outcome-is-preserved-and-a-second-module-may-reach-a-socket.md) — the technical decisions inside the transport

## Supersedes

None.

## Superseded By

None.
