# ADR-0002 — Binance Global is the only venue in scope

## Status

Accepted — Phase 001.

## Context

Supporting several exchanges is a common early ambition and a common source of
permanent complexity. A multi-venue abstraction must reconcile incompatible
symbol conventions, order types, fee models, margin mechanics, rate limit
schemes and error semantics. The abstraction usually ends up expressing the
intersection of what venues share, which is precisely the least interesting
part of any of them.

GLOBIN's value depends on using Binance's actual capabilities well — margin
mechanics, funding, portfolio margin, options — not on being portable.

## Decision

**Binance Global is the only exchange in scope.** This is encoded as
`ExchangeScope.BINANCE_GLOBAL` in `src/globin/project_contract.py`, deliberately
as a single-member enumeration rather than a bare string, so that adding a venue
becomes a visible change to a type rather than an unnoticed literal.

Regional Binance deployments and other exchanges are out of scope. GLOBIN will
integrate the Binance product families that are officially documented and
actually available to the account: Spot, Cross and Isolated Margin, USDⓈ-M
Futures, COIN-M Futures, Options, Portfolio Margin, Portfolio Margin Pro where
genuinely available, and documented Algo Trading facilities.

## Consequences

- Adapters may use Binance-specific semantics directly and precisely. No
  lowest-common-denominator abstraction is required or wanted.
- The system carries concentrated venue risk. An outage, policy change or
  account restriction at Binance affects everything. Phases 284-285 must plan
  for that rather than treat it as unthinkable.
- Should multi-venue support ever be wanted, it is a deliberate re-architecture
  requiring a superseding ADR — not an incremental feature.
- Product breadth within Binance replaces venue breadth as the axis of
  generality, which is why Phases 065-080 are structured per product.
