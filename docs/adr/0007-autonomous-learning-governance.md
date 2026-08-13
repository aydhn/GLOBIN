# ADR-0007 — Autonomous learning is governed by evidence gates

## Status

Accepted — Phase 001.

## Context

GLOBIN is intended to improve itself over time: collect new data, retrain
models, re-optimise parameters, detect drift, and adapt to symbols and regimes
without a human driving every step.

The naive implementation of that ambition is a loop that changes something,
backtests it, and keeps the change if recent profit increased. That loop is not
learning. It is an automated overfitting machine. Given enough iterations it
will reliably discover configurations that would have performed beautifully on
the data it was given and have no predictive content whatsoever. Because it
optimises against the same history repeatedly, its apparent confidence grows
precisely as its real reliability falls.

The danger is amplified by autonomy: a human researcher who tries two hundred
variants at least notices they tried two hundred variants. An automated loop
does not, unless it is built to.

## Decision

Autonomous adaptation is permitted. **Autonomous promotion to live influence is
gated.**

A candidate — a model, a policy or a parameter set — may only affect live
trading after satisfying defined, machine-checkable evidence gates:

1. Leakage-safe training, with all preprocessing fitted inside folds.
2. Held-out validation the candidate did not participate in selecting.
3. Walk-forward evaluation, not a single in-sample fit.
4. Realistic cost assumptions: fees, spread, slippage, funding, borrow.
5. Minimum sample size and statistical power requirements.
6. Robustness across parameter neighbourhoods and market regimes.
7. Risk criteria satisfied, not merely return criteria.
8. Champion-challenger comparison against the current incumbent on identical terms.
9. Versioned promotion with a recorded, auditable justification.
10. A working rollback path.

Corrections for multiple testing and selection bias are mandatory, because the
number of hypotheses an automated system tests is exactly what makes its best
result untrustworthy.

**The system may never weaken its own gates or risk ceilings.** Gate definitions
and the absolute risk bounds of ADR-0008 are outside the search space. An
optimiser that could relax its own constraints is not optimising; it is
escaping supervision.

## Consequences

- Phases 225-240 implement this, and Phase 237 exists specifically to make the
  governance boundary structurally enforced rather than merely documented.
- Adaptation is slower than a naive loop. That is the intended trade.
- Every autonomous change carries an audit trail explaining what evidence
  justified it (Phase 236).
- Some candidates that look excellent in backtest will be refused promotion.
  That is the gate working, not the gate malfunctioning.
- No output of this system is a guarantee. The objective is a measurable
  probabilistic edge after realistic costs, and it must be described that way in
  every report the system produces.
