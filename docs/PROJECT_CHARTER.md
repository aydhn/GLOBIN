# Project Charter

## Mission

GLOBIN is a locally hosted, autonomous cryptocurrency research and trading
system for Binance Global.

Its objective is a **measurable probabilistic edge after realistic costs and
out-of-sample validation** — not prediction accuracy, not backtest returns, and
never a guarantee. Every claim the system makes about its own performance is
framed in those terms.

It is built over a fixed programme of **320 phases**, in order, with each phase
verified and pushed before the next begins.

## Operating context

| Dimension | Reality |
|---|---|
| Host | A single Windows computer, consumer hardware |
| GPU | An NVIDIA GPU may be present; its benefit is measured, not assumed |
| Network | Roughly 100 Mbps wired |
| Cadence | Tens of trades per hour at most |
| Runtime | May run continuously for days |
| Operator | One person, using two launcher files |
| Budget | Zero. The runtime depends only on free components |

This is emphatically not a high-frequency trading context. Latency engineering
would buy nothing at this cadence, while process death, silent state divergence
and a backtest that quietly lied would each be fatal. Architecture effort goes
where the real risk is.

## Scope

**Venue.** Binance Global only ([ADR-0002](adr/0002-binance-global-only-exchange-scope.md)).

**Products**, where officially documented and actually available to the account:
Spot, Cross Margin, Isolated Margin, USDⓈ-M Futures, COIN-M Futures, Options,
Portfolio Margin, Portfolio Margin Pro where genuinely available, documented
Algo Trading facilities, and other officially documented surfaces that provide
material value.

**Capabilities** the finished system is intended to have: market data
acquisition and a point-in-time data platform; technical analysis and feature
engineering; strategy composition; event-driven backtesting with realistic
costs; rigorous research validation; supervised learning and reinforcement
learning where justified; parameter optimisation; governed continual learning;
portfolio and risk management; autonomous orchestration; operator communication
through Telegram; and staged progression to live trading.

## Non-goals

Stating these explicitly prevents them from being re-proposed every few phases.

| Non-goal | Reason |
|---|---|
| Multi-exchange support | Abstraction would express the intersection of venues, discarding what makes Binance useful ([ADR-0002](adr/0002-binance-global-only-exchange-scope.md)) |
| High-frequency or latency-arbitrage trading | Impossible and pointless from a consumer machine at this cadence |
| Cloud or distributed deployment | Contradicts the local-host and zero-budget premises |
| Paid data, compute or infrastructure | [ADR-0003](adr/0003-zero-budget-open-source-dependency-policy.md) |
| Scraping or undocumented endpoints | [ADR-0004](adr/0004-official-apis-only-no-scraping.md) |
| Guaranteed returns, or any claim of certainty | Not achievable; claiming it corrupts every sizing decision downstream |
| A general-purpose trading framework for others | GLOBIN is built for one operator on one machine; generality would cost more than it returns |
| Fully unsupervised capital escalation | Capital increases require evidence and human authorisation ([ADR-0008](adr/0008-immutable-upper-risk-constraints.md)) |

## Governing principles

1. **Evidence over assertion.** Claims about external behaviour come from
   primary sources and are recorded with access dates
   ([`SOURCE_POLICY.md`](SOURCE_POLICY.md)).
2. **Enforcement over intention.** Rules are encoded as tests wherever
   mechanically possible.
3. **Refusal over silent fallback.** When the system cannot act safely, it stops
   and says so.
4. **Bounded autonomy.** The system may adapt within limits it cannot itself
   raise ([ADR-0007](adr/0007-autonomous-learning-governance.md),
   [ADR-0008](adr/0008-immutable-upper-risk-constraints.md)).
5. **Reliability over performance.** Uptime and correctness outrank speed.
6. **Honesty about maturity.** Documentation describes what exists, never what
   is intended.

## The 320-phase programme

Twenty immutable bands of sixteen phases each, from repository foundation
through to live activation. The full index is in
[`../ROADMAP.md`](../ROADMAP.md), and the band skeleton is encoded in
`src/globin/roadmap.py` so document and code cannot drift apart.

Phases are implemented in order. Implementing ahead is a defect, not initiative:
it bypasses the design work the later phase was created to do.

## Definition of a completed phase

A phase is complete only when its tests pass, its documentation matches its
code, no secrets or generated artefacts are committed, and a meaningful commit
is on `master`, pushed to `origin/master`, with local and remote synchronized
and the working tree clean.

The binding checklist is
[`engineering/DEFINITION_OF_DONE.md`](engineering/DEFINITION_OF_DONE.md).
The charter states that a bar exists and why the programme needs one; it does
not keep a second copy of the bar itself
([ADR-0011](adr/0011-documentation-authority-hierarchy.md)).

## Success criteria for the programme

GLOBIN succeeds if, at Phase 320, it can operate unattended for days on the
target machine; demonstrate a validated probabilistic edge after realistic
costs; keep local state reconciled with the exchange; respect its immutable risk
ceilings under every tested condition; adapt under governance without weakening
its own gates; and be operated and recovered by one person using documented
procedures.

It fails if it produces impressive backtests that do not survive out-of-sample
evaluation — which is why Phases 161-176 exist, and why they precede any
machine learning work.
