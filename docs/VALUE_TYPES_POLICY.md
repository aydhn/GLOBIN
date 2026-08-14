# Value types policy

What the five domain value types are, what each refuses, and which operations
they permit. The types live in
[`src/globin/domain/values.py`](../src/globin/domain/values.py); this document is
where a reader finds the rules without reading the code, and
[`tests/contract/test_values_contract.py`](../tests/contract/test_values_contract.py)
compares the two in both directions so that neither can drift.

Written for a contributor about to pass a number across a boundary. If you are
asking "can I add these two together", the answer is in
[Which operations exist](#which-operations-exist), and it is no.

---

## Why these types exist

A number on its own carries no unit. `60000` might be a price in USDT, a
quantity of a token, or a count of milliseconds, and nothing in a signature made
of `Decimal` stops one being passed where another belongs. The failure is quiet:
the arithmetic succeeds and the result is wrong.

The types here are **denominated**, not merely distinct. A `Quantity` knows which
asset it counts; a `Price` knows which market it prices. That is what makes the
second kind of confusion refusable as well as the first — not only "a price where
a quantity belongs", but "a price in USDT compared against a price in EUR".

---

## The types

| Type | Carries | Refuses |
|---|---|---|
| `Side` | `BUY` or `SELL` | nothing; the set is closed |
| `Currency` | `code` | a code outside the alphabet or the length bounds |
| `Symbol` | `base`, `quote` | a half that is not a `Currency`; the same asset on both sides |
| `Quantity` | `amount`, `currency` | an inexact, non-finite, negative or unrepresentable amount |
| `Price` | `amount`, `symbol` | the same, and zero |

`Quantity` is also the money type. Every balance, fee and order size in GLOBIN is
an amount of an asset, so a separate `Money` carrying the same two fields would
need a rule saying when each applies — and that rule is the thing that drifts.

---

## The rules, as constants

Each is published by the module, so a test and this table can agree with the
implementation instead of quoting it.

| Constant | Value |
|---|---|
| `CURRENCY_ALPHABET` | `0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ` |
| `MIN_CURRENCY_CODE_LENGTH` | `2` |
| `MAX_CURRENCY_CODE_LENGTH` | `16` |
| `DECIMAL_ALPHABET` | `0123456789+-.eE` |
| `MAX_SIGNIFICANT_DIGITS` | `28` |
| `MAX_ADJUSTED_EXPONENT` | `30` |
| `SYMBOL_SEPARATOR` | `/` |

### Currency codes

Uppercase letters and digits, two to sixteen characters, case exact. Digits are
permitted because real tickers contain them. Lowercase is refused rather than
normalised, for the reason
[`CONFIGURATION_POLICY.md`](CONFIGURATION_POLICY.md) gives about severity names:
one spelling means one thing to search a log for.

A code is validated for **shape only**. `Currency("ZZZQ")` succeeds. Whether a
venue lists an asset is a capability question answered against the venue
([ADR-0006](adr/0006-product-and-environment-capability-matrix.md)), never a
constant compiled into the domain layer.

### Amounts

An amount is a `Decimal`, and the factories accept a `Decimal`, an `int`, or a
string spelled from `DECIMAL_ALPHABET`. Everything else is refused, in this
order:

| Refused | Because |
|---|---|
| a `float` | `Decimal(1.1)` is `1.100000000000000088817841970012523233890533447265625` — invariant 17 |
| a `bool` | `isinstance(True, int)` is true and `Decimal(True)` is one, so the guard precedes the `int` case |
| `"NaN"`, `"Infinity"`, `" 1 "`, `"1_000"` | `Decimal` reads all four; none is spelled from `DECIMAL_ALPHABET` |
| a non-finite `Decimal` | `NaN` is unequal to itself and ordering one raises `InvalidOperation`, which is not a `globin.errors` type |
| a negative amount, including `-0` | direction is a `Side`, never a sign. `-0` is why the check is `is_signed()` and not `< 0` |
| more than `MAX_SIGNIFICANT_DIGITS` digits | a value that cannot be held exactly would round on its first use — and a value this long usually came from a float |
| a magnitude beyond `MAX_ADJUSTED_EXPONENT` | `1E+100000` renders as 100 001 characters, and the refusal messages interpolate the value |

Zero is a legitimate `Quantity` and never a legitimate `Price`. A zero balance is
an answer; a zero price is a sentinel, and a caller who means "no price" should
say absence.

The whole rule is **context-free**: none of it consults
`decimal.getcontext()`, so the same values are accepted under any thread-local
precision. That is invariant 5 held rather than assumed, and it is why the
magnitude bound is written out rather than delegated to
`Decimal.is_subnormal()`, which is defined against the ambient `Emin`.

---

## Which operations exist

`answers` means the operation returns a value rather than raising.

| Attempt | Outcome |
|---|---|
| `Price < Price, same market` | `answers` |
| `Price < Price, different market` | `ValidationError` |
| `Price == Price, different market` | `answers` |
| `Price < Quantity` | `TypeError` |
| `Price < Decimal` | `TypeError` |
| `Price == Quantity` | `answers` |
| `Quantity < Quantity, same asset` | `answers` |
| `Quantity < Quantity, different asset` | `ValidationError` |
| `hash of a Price` | `answers` |
| `Price + Price` | `TypeError` |
| `Price - Price` | `TypeError` |
| `Price * Quantity` | `TypeError` |
| `Quantity + Quantity` | `TypeError` |
| `negation of a Price` | `TypeError` |
| `float of a Price` | `TypeError` |
| `int of a Quantity` | `TypeError` |
| `round of a Price` | `TypeError` |
| `sum of two Prices` | `TypeError` |
| `Currency < Currency` | `TypeError` |
| `Symbol < Symbol` | `TypeError` |

Three rules generate that table.

**A wrong type gives `TypeError`; a wrong unit gives `ValidationError`.** The
split is deliberate. Returning `NotImplemented` for a wrong type keeps the
reflected-operand protocol working and lets Python write a message naming both
classes, which is adequate because mypy already refuses that call statically. A
wrong unit is different: both operands are the same class, so mypy could not have
refused it, and Python's own message would say only that `<` is unsupported
between two `Price` instances — which tells the caller nothing. `ValidationError`
is the category for "the caller must send different input"
([ADR-0022](adr/0022-error-taxonomy-rooted-in-one-type.md)).

**Equality answers; ordering may refuse.** `__eq__` is called by `in`, by `dict`,
by `set` and by every assertion, so one that raised would make these types
unusable as keys and turn a membership test into an exception. Two prices of
different markets are simply not the same value, and `False` says so. Ordering
carries no such obligation, and "is 5 USDT less than 3 EUR" has no answer worth
inventing.

**There is no arithmetic at all.** Every `Decimal` operation runs under a
thread-local context and may round without saying so —
`Decimal('1E+30') + Decimal('1E-30')` returns `1E+30`, discarding the addend.
Invariant 22 forbids silent data loss, and invariant 17 assigns the precision
policy to Phase 010 by name, so this module cannot define `+` without either
deciding a rounding mode that is not its decision or shipping an operation that
loses data. Comparison is exempt because it is exact: two values compare
correctly whatever the ambient precision, so permitting it settles nothing
Phase 010 owns.

---

## What this policy does not decide

Naming the owning phase is what stops a reader inferring an answer from the
absence of a rule.

| Question | Phase |
|---|---|
| Rounding, tick size, step size, where exact arithmetic is mandatory | 010 |
| Timestamps, clocks and timezones | 009, delivered — [`TIME_POLICY.md`](TIME_POLICY.md) |
| Canonical identifiers, and the register of assets that exist | 011 |
| Serialization and schema evolution for persisted values | 012 |
| The venue spelling of a market, such as the concatenated form | 033-048 |
| Absolute risk ceilings on position and order size | 242 |

The last two are worth spelling out.

**A `Symbol` is a pair, not a string,** and deliberately cannot become one here.
The concatenated form is not decodable without venue knowledge — `BTCUSDT` could
split as `BTC`/`USDT` or `BTCU`/`SDT`, and only a list of known quote assets
settles it. That makes it an encoding requiring a registry rather than a value.
`str(symbol)` renders `BTC/USDT`, with a separator no venue would accept, so a
later phase cannot reach for it and have it appear to work.

**`MAX_ADJUSTED_EXPONENT` is a bound on what can be represented, not a limit on
what may be traded.** It exists so that a value renders in a bounded number of
characters and cannot be a number no venue quotes. A phase that finds it too
tight should widen it with the case that showed why, not delete it.
