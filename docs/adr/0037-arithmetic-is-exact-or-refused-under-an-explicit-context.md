# ADR-0037 — Arithmetic is exact or refused, under an explicitly built context, and rounding is always an argument

## Status

Accepted — Phase 010.

**Date:** 2026-08-14

## Context

`ROADMAP.md` assigns Phase 010 to *Decimal and Numeric Precision Policy*: decide
where exact arithmetic is mandatory versus floating point, and define rounding
and tick-size behaviour. Three earlier records deferred to it by name —
[ADR-0030](0030-domain-values-are-denominated-wrappers-over-decimal.md),
[ADR-0031](0031-value-types-compare-but-do-not-compute.md) and
[ADR-0035](0035-milliseconds-are-a-floored-projection.md) — and
[`ENGINEERING_CONTRACT.md`](../engineering/ENGINEERING_CONTRACT.md) invariant 17
named it as the owner of the unanswered question.

ADR-0031 left `Price` and `Quantity` with comparison and no arithmetic. Its
reasoning was that every `Decimal` operator reads a thread-local context and may
round without saying so, so defining `+` would mean either choosing a rounding
mode that was not Phase 008's to choose or shipping an operation that loses data.
That reasoning was correct and remains correct about *operators*.

It also rejected the exact-or-refuse design that this record adopts, and the
reason it gave was specific: that implementing it would mean calling
`decimal.localcontext` inside a domain method, mutating thread-local state and
breaking invariant 5.

**That premise is false, and the falsity is measurable.** `localcontext` does
swap the thread's context. A `Context` *method* — `context.add(a, b)`,
`context.divmod(a, b)` — does not: it takes its precision, exponent range and
traps from the object it is called on and touches nothing thread-local.
Entry S-03 in [`phase_010_sources.md`](../research/phase_010_sources.md) records
the observation: after such a call, `decimal.getcontext()` returns the same
object with its precision unchanged and its flags still empty.

So the option ADR-0031 declined is available on terms it did not consider, and
this record supersedes it rather than merely extending it — because ADR-0031's
decision, stated as "value types compare but do not compute", is no longer what
the codebase does.

## Decision

**1. There are two numeric regimes, and the boundary is stated as a rule.**
Exact arithmetic is **mandatory** for anything that is, becomes, or decides an
amount of an asset — balances, sizes, prices sent to a venue, notional, fees, and
every refusal computed from any of them. `float` is **permitted** only where a
number is a measurement or a score whose result is never itself money. Two
corollaries make the line checkable: a `float` may never be the last
transformation before a venue, a ledger or a persisted record; and a `float` may
never decide a refusal.

**2. Arithmetic is exact or it is refused.** `add`, `subtract` and `multiply` in
[`globin.domain.precision`](../../src/globin/domain/precision.py) return the
mathematically exact result or raise `ValidationError`. They take no rounding
mode because they never round. `Quantity.__add__` and `Quantity.__sub__` are
defined in terms of them.

**3. No module under `src/globin` reads the ambient decimal context.** Every
operation runs on a `Context` built for that call, with `Inexact`,
`InvalidOperation`, `DivisionByZero`, `Overflow` and `Underflow` trapped. The
context is built by a function rather than held as a constant, because a
`Context` accumulates flags (S-04) and would otherwise be mutable global state.
`tests/architecture/test_precision_discipline.py` refuses `getcontext`,
`setcontext` and `localcontext` anywhere in the package, including inside a
function body.

**4. Rounding is always an argument, and there is no default.** Every operation
that can lose information takes a required, keyword-only `Rounding`. A default is
what makes a rounding decision invisible at the call site.

**5. `Price` gains no arithmetic.** The difference of two prices is signed and
`Price` is strictly positive; the sum of two prices is not a price. Valuing a
quantity at a price is `notional()`, a named function rather than `*`, because
the result changes denomination and an operator cannot show that. Signed money is
Phases 155-156.

**6. The rounding vocabulary is four members, not `decimal`'s eight.** `FLOOR`,
`CEILING`, `HALF_EVEN` and `EXACT`. The directional pair is spelled by direction
rather than as `DOWN`/`UP` so that its meaning does not silently change when a
signed money type arrives.

## Consequences

`Quantity` now adds and subtracts, which is the operation the system actually
needed; a balance check becomes a fact about the type rather than something a
caller must remember to write.

What this costs:

- **An exact result can be unrepresentable.** `quantity("1E+30") + quantity("1E-30")`
  has an exact 61-digit sum, which is more digits than a `Quantity` may carry, so
  it raises. This is the design working, and it will arrive as a bug report. It
  has a named unit test whose message explains it.
- **Every call site that rounds is longer.** `align_price(p, tick=t, rounding=Rounding.FLOOR)`
  is more to write than `round(p, 2)`. That is the point, and it is the cost.
- **A new domain module.** `precision.py` is a second place to look, and the
  import direction between it and `values.py` is now load-bearing: `values`
  imports `precision`, never the reverse.
- **Three copied constants.** `precision` restates the digit bound, the magnitude
  bound and the decimal alphabet that `values` publishes, because it must not
  import `values`. [`SOURCE_OF_TRUTH.md`](../engineering/SOURCE_OF_TRUTH.md)
  permits that only as a tripwire, so a contract test compares each pair.

Enforcement: the architecture test above, the contract test binding
[`PRECISION_POLICY.md`](../PRECISION_POLICY.md) to the code, and a property test
asserting that a hostile ambient context changes no answer.

## Alternatives Considered

**Keep ADR-0031 as it stands.** The most conservative option, and the one this
record had to beat rather than ignore. It was rejected because ADR-0031 itself
named Phase 010 as the phase that would decide, so leaving the operators absent
would not be caution — it would be the deferral never ending. Its stated
objection is also no longer true, which is the strongest possible reason to
revisit a decision.

**Use `localcontext` and accept the thread-local swap.** The obvious
implementation, and the one ADR-0031 rejected on correct grounds. Refused for
those same grounds: it would leave GLOBIN's answers dependent on what a caller
had configured, and a domain method that mutates process-wide state is invariant
5's exact prohibition. `Context` methods make the trade unnecessary.

**Give every operation a default rounding mode of `HALF_EVEN`.** Convenient, and
the reason it is refused is that it is convenient. A default is applied by call
sites that never considered rounding at all, which is precisely the population
whose rounding most needs to have been considered.

**Define `Price.__mul__(Quantity)` instead of `notional()`.** Shorter to write
and worse to read: a reader of `a * b` cannot see that the answer is denominated
in a third currency. The operator would also make `Price` look arithmetically
complete while `+` and `-` remained absent, which is a more confusing surface
than having none.

**Adopt `decimal`'s eight rounding modes wholesale.** Fewer decisions to defend,
and it would admit `ROUND_HALF_UP` — which biases upward and is wrong for
exchange quantities — with nobody having argued for it. The same reasoning
`errors.py` uses for having five fault domains rather than however many occur to
someone.

**Give tick sizes and step sizes separate types.** They differ in what they are
applied to, not in what they are, so two identical types would need a rule for
which applies where — the rule ADR-0030 refused to write when it declined a
separate `Money` type.

## Risks and Trade-offs

**The characteristic failure is a caller reaching around the module.** Somebody
who wants `a * 2` and cannot have it writes `Decimal(str(q.amount)) * 2` instead.
The observable signal is a `.amount` read outside `globin.domain`, which is why
that is now an architecture test rather than a convention — and it is ADR-0030's
own predicted failure mode, promoted to a gate.

**The second risk is over-refusal.** Exact-or-refuse means a legitimate
calculation can raise because its intermediate needed 30 digits. If that happens
often in a later phase, the right response is to widen `MAX_SIGNIFICANT_DIGITS`
with the case that showed why — and to re-derive `EXACT_PRECISION`, which a unit
test recomputes from the published bounds so the omission cannot pass silently.

**The third is scope.** A real Binance tick size appearing as a constant in
`precision.py` would mean this phase had started doing Phases 049-050's work.
Nothing here contains a venue constant, and the integration test says in a comment
why its literals are literals.

## References

- [`ROADMAP.md`](../../ROADMAP.md) — Phase 010
- [`docs/PRECISION_POLICY.md`](../PRECISION_POLICY.md)
- [`docs/research/phase_010_sources.md`](../research/phase_010_sources.md) — S-01 to S-09
- [`docs/engineering/ENGINEERING_CONTRACT.md`](../engineering/ENGINEERING_CONTRACT.md), invariants 5, 17 and 22
- [`docs/engineering/SOURCE_OF_TRUTH.md`](../engineering/SOURCE_OF_TRUTH.md)
- [ADR-0030](0030-domain-values-are-denominated-wrappers-over-decimal.md)
- [ADR-0035](0035-milliseconds-are-a-floored-projection.md)
- [ADR-0038](0038-a-tick-size-and-a-step-size-are-one-undenominated-increment.md)

## Supersedes

[ADR-0031](0031-value-types-compare-but-do-not-compute.md).

## Superseded By

None.
