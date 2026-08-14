# ADR-0038 — A tick size and a step size are one undenominated `Increment`, aligned by `divmod`

## Status

Accepted — Phase 010.

**Date:** 2026-08-14

## Context

Phase 010 owns tick-size behaviour. A venue publishes two grid spacings for a
market: a **tick size**, which a price must be a multiple of, and a **step
size**, which a quantity must be a multiple of. Both are exact decimals, both are
strictly positive, and both are applied by the same operation.

Three questions had to be answered before the mechanism could be written, and
[ADR-0037](0037-arithmetic-is-exact-or-refused-under-an-explicit-context.md)
answers none of them: whether they are one type or two, whether the type carries
what it applies to, and how a value is actually moved onto the grid.

The third is not a detail. The obvious implementation is
`amount.quantize(step, rounding=...)`, and it is wrong here for a reason that is
easy to miss.

## Decision

**1. One type.** `Increment` carries a single strictly positive `Decimal`. A tick
size and a step size are the same mathematical object; which one a given
`Increment` *is* depends on what it is applied to.

Two types with identical fields would need a rule saying which applies where, and
that rule is the thing that drifts —
[ADR-0030](0030-domain-values-are-denominated-wrappers-over-decimal.md)'s
argument for having no separate `Money` type, which holds here unchanged. The
distinction is carried instead by the two call sites: `align_price(held, tick=…)`
and `align_quantity(held, step=…)` are separately named, and each keyword says
which grid it means.

**2. It carries no denomination.** No `Symbol`, no `Currency`. A denomination
invented in this phase would be a guess about the shape of the instrument
registry that **Phases 049-050** own. ADR-0030 already set this split: shape is
validated in the domain, membership is answered against the venue.

**3. Alignment uses `divmod`, not `quantize`.** The steps are: divide the
magnitude by the step to get an exact integer quotient and a remainder; decide
from the remainder and the mode whether to take the next step up; multiply the
step count back by the step.

This matters for two reasons, both measured in
[`phase_010_sources.md`](../research/phase_010_sources.md):

- **`quantize` aligns to a number of decimal places, not to a grid.** It cannot
  express a step of `25` or `2.5` at all, and venues publish such steps.
- **`divmod` preserves the increment's own exponent** (S-06). The integer
  quotient has exponent zero, so multiplying it by a step of `0.00010000` yields
  a value spelled to eight places. Those trailing zeros are the venue's statement
  of its precision, and ADR-0030 refused a scaled-integer representation
  precisely so as not to discard them.

**4. An oversized quotient is refused.** `divide-integer` signals
`DivisionImpossible` when the quotient exceeds the context's precision (S-07).
That signal is translated into a `ValidationError` naming the operands, rather
than caught and worked around.

**5. Alignment is defined for magnitudes only.** A negative amount is refused.
`Decimal`'s `divmod` truncates toward zero, so `FLOOR` and `CEILING` would each
need a second implementation below zero — a decision belonging to the phase that
introduces signed money, which is **155**.

## Consequences

One type and two call sites means a caller cannot pass a tick size where a step
size belongs and be refused for it. That is a real gap, accepted deliberately:
catching it needs the instrument registry, and inventing half of that registry
here would be worse than the gap.

`Increment` validates its step's shape against bounds restated from `values.py`,
which is a copy, which is a cost. It is licensed as a tripwire and compared by a
contract test.

The alignment implementation is longer than a `quantize` call and does not look
like the idiom a reader expects, so its docstring says why in two sentences. A
future contributor "simplifying" it to `quantize` would pass every test except
the ones using a step of `25` — which is why such a step is in the property
strategies rather than only in prose.

## Alternatives Considered

**`Decimal.quantize` with an exponent.** The idiomatic spelling, and it cannot
express a non-power-of-ten grid. A venue quoting in increments of `25` is
ordinary, and a mechanism that handles only some real grids is a mechanism that
will be worked around at the first one it cannot handle.

**Separate `TickSize` and `StepSize` types.** More type safety in principle. In
practice both wrap one `Decimal` with identical validation, so the pair buys a
distinction that only the call site can actually check, at the cost of the
"which applies where" rule ADR-0030 warns about.

**An `Increment` carrying its `Symbol`.** Would let `align_price` verify that the
tick belongs to the market. Refused because Phase 010 does not know how a market
is identified — that is Phase 011 — nor where filters come from, which is Phases
049-050. Building it now would mean rebuilding it then.

**Integer scaling: represent everything as a count of increments.** Fast and
exact, and it discards the venue's stated precision, which ADR-0030 already
refused on the same ground.

**Allow negative magnitudes and define the modes over them.** Tempting for
symmetry. Refused because there is no signed money type for the result to be, so
the definition could not be exercised by anything and would be written against an
imagined caller.

## Risks and Trade-offs

**The characteristic failure is a tick applied to the wrong market.** Nothing in
this phase can catch it. The observable signal is an aligned price that a venue
still rejects as off-tick, and the phase that must close the gap is 082, which
owns filter validation. Named here so that the gap is a known one rather than a
surprise.

**The second is the "simplification" to `quantize`** described above. The
countermeasure is a coarse, non-decimal step in the property strategies, which
fails immediately if the implementation changes shape.

**The third is a step arriving as a `float`.** `increment(0.01)` is refused by
type, but `increment(Decimal(0.01))` arrives already converted and is 58 digits
long (S-08). The digit bound catches it, which is why the bound is a refusal
rather than a guideline.

## References

- [`docs/PRECISION_POLICY.md`](../PRECISION_POLICY.md)
- [`docs/research/phase_010_sources.md`](../research/phase_010_sources.md) — S-06 to S-08
- [ADR-0030](0030-domain-values-are-denominated-wrappers-over-decimal.md)
- [ADR-0037](0037-arithmetic-is-exact-or-refused-under-an-explicit-context.md)
- [`ROADMAP.md`](../../ROADMAP.md) — Phases 049-050, 082, 155

## Supersedes

None.

## Superseded By

None.
