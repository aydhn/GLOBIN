# ADR-0008 — Upper risk bounds are immutable and outside the search space

## Status

Accepted — Phase 001.

## Context

GLOBIN will eventually place real orders on margin and derivatives products,
adjusting its own behaviour without a human in the loop for each decision. Two
distinct kinds of limit exist in such a system, and conflating them is how
autonomous trading systems destroy accounts.

The first kind is a **tunable parameter**: a position size multiplier, a
per-strategy allocation, a stop distance. These should adapt — that is the point
of the research programme.

The second kind is an **absolute ceiling**: the maximum leverage the system may
ever use, the drawdown at which it must stop, the total exposure it may never
exceed. These exist to bound the worst case, including the worst case caused by
the system's own malfunction.

If an optimiser can raise a ceiling, the ceiling is not a ceiling — it is just
another parameter, and it will be raised, because relaxing a binding constraint
almost always improves a backtest.

## Decision

Risk constraints are classified into three tiers, and the classification is
part of the type system rather than a convention:

| Tier | Who may change it | Example |
|---|---|---|
| **Immutable ceiling** | Only the human owner, by editing source and committing | Maximum leverage; maximum total drawdown before halt; kill-switch thresholds |
| **Policy limit** | Governed change with evidence, per ADR-0007 | Per-strategy capital allocation |
| **Tunable parameter** | Optimisation and adaptation | Position sizing coefficients |

Rules:

1. No strategy, model, optimiser, reinforcement learning policy or autonomous
   process may raise an immutable ceiling. This must be structurally impossible,
   not merely prohibited by documentation.
2. Every order passes a pre-trade risk gate that cannot be bypassed, disabled at
   runtime, or configured away by a strategy.
3. Ceilings are enforced at the last point before submission, so a defect
   anywhere upstream — including in the risk-aware sizing logic itself — still
   cannot produce an order that violates them.
4. A breach of an immutable ceiling halts trading. It does not warn and
   continue.
5. Reward functions in reinforcement learning may include risk penalties, but
   penalties are not a substitute for hard limits. A penalty is a preference; a
   ceiling is a boundary.

This ADR does not restrict which trading features may be built. It restricts
only the ability of automated optimisation to remove the protections that bound
catastrophic loss.

## Consequences

- Phase 242 implements ceiling enforcement, and Phase 253 implements the
  unbypassable pre-trade gate.
- Some theoretically optimal configurations will be unreachable. That is
  intended: the ceiling encodes a loss the owner is unwilling to risk regardless
  of expected value.
- Raising a ceiling requires a human editing source and committing to `master`,
  which leaves a permanent, reviewable record.
- Risk logic must be simple enough to audit by reading. Complexity in the
  component that prevents catastrophe is itself a risk.
