# Precision policy

Where exact arithmetic is mandatory, how a magnitude rounds, and what a tick size
and a step size are. Delivered by Phase 010; the code is
[`src/globin/domain/precision.py`](../src/globin/domain/precision.py).

This document owns the precision rules. What the value types *are* is
[`VALUE_TYPES_POLICY.md`](VALUE_TYPES_POLICY.md); how a timestamp is projected
onto a coarser grid is [`TIME_POLICY.md`](TIME_POLICY.md).

---

## The problem this exists to solve

Every `decimal.Decimal` **operator** reads a thread-local context.
`Decimal('1E+30') + Decimal('1E-30')` returns `1E+30` under the default context,
discarding the addend without a word, and a caller who has set `prec=5` changes
what every other module computes.

That is two failures in one expression: the silent data loss
[`ENGINEERING_CONTRACT.md`](engineering/ENGINEERING_CONTRACT.md) invariant 22
forbids, and the hidden global state invariant 5 forbids.

Phase 008 responded by defining no arithmetic operators at all and naming this
phase as the owner of the answer ([ADR-0031](adr/0031-value-types-compare-but-do-not-compute.md)).

---

## The five rules

### 1. Two regimes, with a one-way door between them

**The exact regime is mandatory** for anything that is, becomes, or decides an
amount of an asset: balances, order sizes, prices sent to a venue, notional,
fees, cost basis, and every refusal computed from any of them. The carrier is
`Decimal`, held inside a `Quantity` or a `Price`.

**The approximate regime is permitted** for statistics over amounts whose result
is never itself money: indicator values, model features, correlations, optimiser
objectives, plots. The carrier is `float`.

The test is not "is this number large" but **"does an error here cost money that
cannot be recovered?"** An indicator value feeds a decision that is then *sized*,
and the sizing is exact. A price sent to a venue is not sized again.

Two corollaries make that line checkable rather than aspirational:

- A `float` may never be the last transformation before a venue, a ledger or a
  persisted record.
- A `float` may never decide a refusal. A balance-sufficiency check computed in
  binary floating point is a check that can flip.

A value may leave the exact regime. It re-enters only through decimal *text*.
There is no `float(Price)`, no `Price.as_float()`, and none will be added.

### 2. Arithmetic is exact, or it is refused

`add`, `subtract` and `multiply` return the mathematically exact result or raise
`ValidationError`. They take no rounding mode, because they never round.

Nothing in the module uses an operator, and nothing reads the thread-local
context. Every operation is a method on a `decimal.Context` built for that call.
A `Context` method takes its precision, its exponent range and its traps from the
object it is called on, and touches no thread-local state at all.

That last fact is measured, not assumed — it is entry S-03 in
[`research/phase_010_sources.md`](research/phase_010_sources.md), and it is why
ADR-0031's objection does not apply. That objection was about
`decimal.localcontext`, which does swap thread-local state; a `Context` method
does not.

### 3. There is no default rounding mode anywhere in GLOBIN

Every operation that can lose information takes a **required, keyword-only**
`rounding` argument. A default is what makes a rounding decision invisible at the
call site, so there is none.

| Mode | `decimal` equivalent | What it is for |
|---|---|---|
| `FLOOR` | `ROUND_FLOOR` | Making a value acceptable to a venue: a quantity onto its step, a bid onto its tick. Never asks for more than exists. |
| `CEILING` | `ROUND_CEILING` | Making a value acceptable to a charge: a fee owed, a margin requirement, a minimum notional. Never reserves too little. |
| `HALF_EVEN` | `ROUND_HALF_EVEN` | Reporting and statistics over many values, where a directional bias accumulates into a number somebody will quote. |
| `EXACT` | none | Not a rounding mode: the assertion that the value is already on the grid. Refuses if it is not. |

Three things about that table are decisions rather than description.

**`ROUND_FLOOR` and `ROUND_CEILING`, not `ROUND_DOWN` and `ROUND_UP`.** They are
identical for every value GLOBIN currently admits, because `Quantity` and `Price`
are non-negative. The directional pair is chosen so that the meaning does not
silently change when Phases 155-156 introduce signed money.

**Four modes, not `decimal`'s eight.** `ROUND_UP`, `ROUND_HALF_UP`,
`ROUND_HALF_DOWN` and `ROUND_05UP` each have a defensible use somewhere and none
here. Admitting a mode nobody argued for is how a rounding decision gets made by
accident.

**`EXACT` is a member rather than a separate function**, so that every call site
names a mode and there is no second spelling of "do not round". A caller who
would rather branch than catch uses `is_aligned`.

### 4. A tick size and a step size are one type, carrying no denomination

`Increment` is a strictly positive, finite `Decimal` grid spacing. One type, not
two: a tick and a step are the same mathematical object, and two types with
identical fields would need a rule saying which applies where — which is the rule
that drifts. [ADR-0030](adr/0030-domain-values-are-denominated-wrappers-over-decimal.md)
makes exactly this argument for having no separate `Money` type.

It carries no `Symbol` and no `Currency`, because a denomination invented here
would be a guess about the shape of the instrument registry that **Phases
049-050** own. Which one an `Increment` *is* depends on what it is applied to, and
`align_price` and `align_quantity` are separately named so the call site says so.

Alignment performs **no division**. It uses `Context.divmod`, which is exact for
every admissible pair and yields an integer quotient, so multiplying back by the
step reproduces the step's own exponent. An increment of `0.00010000` therefore
produces values spelled to eight places: the trailing zeros are the venue's
statement of its precision, and ADR-0030 refused a scaled integer representation
precisely because it would discard them.

### 5. The ambient context is unreachable, and that is enforced

[`tests/architecture/test_precision_discipline.py`](../tests/architecture/test_precision_discipline.py)
parses every module under `src/globin` and refuses `decimal.getcontext`,
`decimal.setcontext` and `decimal.localcontext` anywhere, including inside a
function body. The behavioural tests check that a hostile ambient context changes
no answer; this checks that no future module can start depending on one.

The same file carries a second rule, which is ADR-0030's own stated risk turned
into a gate: **no module outside `globin.domain` may read `.amount` off a value.**
That record predicts the characteristic failure of denominated types as "a helper
appearing that strips `.amount` so the rest can work in raw `Decimal`". There are
no such reads today, so it is a tripwire from its first commit.

---

## Published bounds

| Constant | Value |
|---|---|
| `EXACT_PRECISION` | `128` |
| `EXACT_MIN_EXPONENT` | `-999999` |
| `EXACT_MAX_EXPONENT` | `999999` |
| `MAX_INCREMENT_DIGITS` | `28` |
| `MAX_INCREMENT_EXPONENT` | `30` |
| `INCREMENT_ALPHABET` | `0123456789+-.eE` |

`EXACT_PRECISION` is derived rather than chosen. An amount `values` admits carries
at most 28 significant digits with an adjusted exponent within ±30, so its largest
place value is `1E+30` and its smallest is `1E-57`. The exact sum of two such
amounts spans 88 decimal places plus one for a carry; the exact product needs at
most 56 digits; the exact integer quotient of an amount by an increment needs at
most 61. One hundred and twenty-eight clears all three, and a unit test rederives
the worst case from the published bounds so the arithmetic above is checked rather
than believed.

The last three constants are deliberate copies of bounds
[`VALUE_TYPES_POLICY.md`](VALUE_TYPES_POLICY.md) owns. `precision` is the inner
module and must not import `values`, and
[`SOURCE_OF_TRUTH.md`](engineering/SOURCE_OF_TRUTH.md) permits a copy only as a
tripwire — so a contract test compares each pair and fails when they diverge.

---

## What this policy does not decide

Naming the owning phase is what stops a reader inferring an answer from the
absence of a rule.

| Question | Phase |
|---|---|
| The venue spelling of a market, and its real tick and step values | 049-050 |
| Whether an order satisfies a venue's filters | 082 |
| Fee schedules, tiers, and how a fee is charged | 148 |
| A signed money type — profit and loss, spread, drawdown | 155-156 |
| Whether a ratio, such as a sizing fraction, gets its own type | 243 |
| The numeric type indicators and models use, and their tolerance | 113-128 |
| How a `Decimal`, an `Increment` or a `Rounding` is serialised | 012, delivered — [`SERIALIZATION_POLICY.md`](SERIALIZATION_POLICY.md) |
| Canonical identifiers for markets and assets | 011, delivered — [`IDENTIFIER_POLICY.md`](IDENTIFIER_POLICY.md) |
| Absolute risk ceilings on position and order size | 242 |
| Bit-identical reproducibility of a float computation across hosts | 158 |
| Timestamps, clocks and millisecond conventions | 009, delivered — [`TIME_POLICY.md`](TIME_POLICY.md) |

The boundary with Phase 009 is worth stating in one sentence, because it is the
collision a reader is most likely to raise: **Phase 010 decides how a magnitude
rounds; Phase 009 decides how a coordinate is projected onto a coarser grid.**
