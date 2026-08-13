# ADR-0006 — Binance integration is driven by a product and environment capability matrix

## Status

Accepted — Phase 001.

## Context

The intuitive model of an exchange integration is one client, one set of
credentials, and a switch that selects "test" or "live". Applied to Binance,
that model is wrong, and the ways it is wrong are dangerous.

Phase 1 research established the following from primary sources:

- **Demo Mode** runs on production infrastructure with virtual balances, uses
  keys issued through a separate demo portal, and is documented for **Spot
  only** (`docs/research/phase_001_sources.md`, S-05).
- **Spot Testnet** is separate infrastructure with its own keys, is reset
  roughly monthly without notice, and serves **only `/api` endpoints — `/sapi`
  is unsupported** (S-06). Since Margin and Wallet functionality lives under
  `/sapi`, those products cannot be exercised there at all.
- **Futures Testnet** is a distinct environment again, with its own base URLs
  and credentials.
- Binance's own Python SDK is not one package but roughly twenty-five
  independent per-product distributions (S-07). The vendor models products as
  separately versioned units.

So "testnet", "demo" and "production" are three different environment classes,
not two, and coverage of the non-production classes varies per product. A system
that assumes one universal non-production endpoint would, in the best case, fail
loudly. In the worst case it would silently route what the operator believed was
paper trading to a production endpoint holding real funds.

## Decision

GLOBIN models **product** and **environment** as independent dimensions, and
every operation is routed through an explicit **capability matrix** that answers:
does this product support this environment, with which base URLs, which
credentials, and which endpoint subset?

Rules that follow from this:

1. Environment classes are distinct types: production, testnet, demo, and
   internal simulation. They are never conflated, and "not production" is never
   treated as a single thing.
2. Credentials are scoped to a product and environment pair. A demo key is not a
   testnet key and neither is a live key.
3. If the matrix has no entry for a requested product and environment
   combination, the operation is **refused**. It is never silently downgraded,
   and never falls back to production.
4. Paper trading is a composition of per-product decisions — demo here, testnet
   there, internal simulation where neither exists — not a global mode.
5. The matrix is built from documented evidence and is re-verified when Binance
   documentation changes, not assumed once and trusted forever.

## Consequences

- Phase 036 exists specifically to build this matrix, and Phases 033-035 exist
  to gather what it needs.
- Adapters are per product (Phases 065-080), mirroring the vendor's own
  structure rather than fighting it.
- Some products will have no non-production environment. For those, internal
  simulation is the only pre-live option, and that limitation must be stated
  plainly to the operator rather than hidden.
- Because testnet state resets monthly, no durable research or reconciliation
  history may be founded on testnet data.
- The refusal-by-default rule in point 3 is the single most important safety
  property in this ADR. It is what prevents an unmapped combination from
  reaching real capital.
