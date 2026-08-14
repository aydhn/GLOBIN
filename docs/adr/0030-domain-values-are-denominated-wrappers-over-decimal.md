# ADR-0030 — Domain values are denominated frozen wrappers over `Decimal`, never subclasses of it

## Status

Accepted — Phase 008.

**Date:** 2026-08-14

## Context

A number carries no unit. `60000` might be a price in USDT, a quantity of a
token, or a count of milliseconds, and a signature made of `Decimal` cannot tell
one from another. The failure is quiet: the arithmetic succeeds and the answer is
wrong.

`ENGINEERING_CONTRACT.md` invariant 17 already says that prices, quantities,
balances and fees are values where representation error is a correctness problem,
and assigns the *precision policy* to Phase 010 by name. Phase 008 is the phase
that gives those values types.

Three measurements shaped what follows, and all three are recorded in
[`docs/research/phase_008_sources.md`](../research/phase_008_sources.md).

- `Decimal('NaN')` constructs without complaint, `==` against it is always false,
  and `<`, `<=`, `>`, `>=` raise `InvalidOperation`.
- `Decimal(1.1)` is exactly
  `1.100000000000000088817841970012523233890533447265625` — fifty-two digits.
- Subclassing `Decimal` defeats the whole exercise. With `class P(Decimal)` and
  `class Q(Decimal)`, `P('2') + Q('3')` returns a plain `Decimal` and
  `P('2') == Q('2')` is `True`.

## Decision

**1. Five types, in one domain module, and nowhere else.**
`Side`, `Currency`, `Symbol`, `Quantity` and `Price` live in
`src/globin/domain/values.py`. There is no `ports/`, `application/`, `adapters/`
or `runtime/` counterpart, breaking the shape Phases 006 and 007 set. Those
phases had a world-facing concern — a log record must be written, configuration
must be read — so each needed a port to name what the core wanted from outside.
Nothing external supplies a `Price`. A port with no implementer would be the
scaffolding `REPOSITORY_LAYOUT.md` forbids, and the composition root would have
nothing to wire.

**2. The carrier is `Decimal`, wrapped and never subclassed.** A subclass would
make `Price('2') == Quantity('2')` true, which is the confusion this phase
exists to prevent. An integer scaled by a fixed number of places was the other
candidate and is refused because choosing the scale *is* the precision policy,
and because collapsing `"0.00010000"` to an integer discards the venue's stated
precision — the narrowing invariant 22 calls silent data loss.

**3. Values are denominated.** A `Quantity` carries the `Currency` it counts and
a `Price` carries the `Symbol` it prices. "Units" in the phase title is the
denomination: a bare magnitude in a wrapper would refuse a price where a quantity
belongs and still permit a price in USDT to be compared against one in EUR.

**4. A `Symbol` is a pair of currencies, never a string.** The concatenated venue
spelling is not decodable without venue knowledge — `BTCUSDT` could split as
`BTC`/`USDT` or `BTCU`/`SDT`, and only a list of known quote assets settles it.
That makes it an encoding requiring a registry rather than a value, which is
simultaneously Phase 011's and Phases 033-048's. `str(symbol)` renders `BTC/USDT`
with a separator no venue would accept, so a later phase cannot reach for it and
have it appear to work.

**5. Shape is validated; membership is not.** `Currency("ZZZQ")` succeeds. Whether
a venue lists an asset is a capability question answered against the venue
([ADR-0006](0006-product-and-environment-capability-matrix.md)), and the register
of canonical identifiers is Phase 011.

**6. Direction is a `Side`, so an amount is never negative.** `Quantity` refuses a
negative amount and `Price` refuses zero as well. Collapsing direction into the
sign of a number is how a sell becomes a buy under a stray negation.

**7. Refusal is context-free.** Every rule is checked against a constant this
module publishes, never against `decimal.getcontext()`. `Decimal.is_subnormal`
was in the first draft and was replaced by an explicit bound on
`Decimal.adjusted` for exactly this reason: subnormality is defined against the
ambient `Emin`, and a refusal that moves when a caller changes a thread-local
setting is the hidden global state invariant 5 forbids.

**8. `Quantity` is the money type.** Every balance, fee and order size in GLOBIN
is an amount of an asset. A separate `Money` carrying the same two fields would
need a rule for when each applies, and that rule is the thing that drifts.

## Consequences

Every call site that handles a price or a quantity now carries its denomination.
That is the cost of the guarantee, and it is real: a function taking
`(Decimal, Decimal)` becomes one taking `(Price, Quantity)`, and a caller holding
only a magnitude has to say what it is a magnitude of.

Constructing a value from a `float` is impossible. Phases that read a venue
response must keep the exact text and pass that, which is invariant 17 enforced
rather than stated.

`MAX_ADJUSTED_EXPONENT` bounds magnitude at `1E+30`. This is not a risk ceiling
— those are Phase 242 — and not a rounding rule. It exists because
`format(Decimal('1E+100000'), 'f')` renders 100 001 characters and the refusal
messages interpolate the value, so two absurd amounts compared against each other
would build an enormous string on the error path. A later phase finding it too
tight should widen it with the case that showed why.

`docs/VALUE_TYPES_POLICY.md` now owns the register, and
`tests/contract/test_values_contract.py` compares it to the code in both
directions — executing each documented operation rather than comparing strings.

## Alternatives Considered

**Subclass `Decimal`.** It would make arithmetic and comparison work immediately
and read naturally. It was refused on measurement rather than principle:
`P('2') == Q('2')` is `True` and `P('2') + Q('3')` is a bare `Decimal`, so a
`Price` and a `Quantity` would be interchangeable exactly where it matters.

**A scaled integer.** Exact, fast, and a common choice in exchange code. Refused
because the scale has to be chosen, and choosing it is Phase 010's sentence in
the roadmap almost word for word.

**Bare magnitudes with no denomination.** Simpler call sites, and it catches the
kind-confusion. It does not catch the unit-confusion, which is the harder half
and the one that survives review.

**A separate `Money` type.** Rejected under decision 8: two types with identical
fields need a rule for choosing between them.

**A `str` subclass for `Currency`.** `Currency("BTC") == "BTC"` would be true and
the value would pass anywhere a string is wanted — the same argument
[ADR-0022](0022-error-taxonomy-rooted-in-one-type.md) makes about inheriting from
builtin exceptions.

## Risks and Trade-offs

The characteristic failure is denomination becoming ceremony: call sites carrying
a `Symbol` through code that never reads it, and a helper appearing that strips
`.amount` so the rest can work in raw `Decimal`. The observable signal is that
helper. If it appears, the types have become a tax rather than a guarantee, and
the answer is to move the operation into this module rather than to route around
it.

The second risk is that `MAX_ADJUSTED_EXPONENT` and `MAX_SIGNIFICANT_DIGITS` are
judgements. Both are far outside anything a venue quotes, but both are numbers
somebody chose. The signal that one is wrong is a legitimate value being refused;
the answer is to widen it with that value written down, not to delete the bound.

## References

- [`docs/VALUE_TYPES_POLICY.md`](../VALUE_TYPES_POLICY.md)
- [`docs/research/phase_008_sources.md`](../research/phase_008_sources.md)
- [`docs/engineering/ENGINEERING_CONTRACT.md`](../engineering/ENGINEERING_CONTRACT.md), invariants 5, 17 and 22
- [ADR-0006](0006-product-and-environment-capability-matrix.md)
- [ADR-0022](0022-error-taxonomy-rooted-in-one-type.md)
- [ADR-0027](0027-configuration-is-a-frozen-dataclass-validated-at-the-boundary.md)
- [ADR-0031](0031-value-types-compare-but-do-not-compute.md)

## Supersedes

None.

## Superseded By

None.
