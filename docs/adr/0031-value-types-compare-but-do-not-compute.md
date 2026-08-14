# ADR-0031 — Value types compare but do not compute; a wrong type returns `NotImplemented` and a wrong unit raises

## Status

Superseded by [ADR-0037](0037-arithmetic-is-exact-or-refused-under-an-explicit-context.md) — Phase 008.

**Date:** 2026-08-14

## Context

[ADR-0030](0030-domain-values-are-denominated-wrappers-over-decimal.md) settles
what the value types *are*. This settles what may be done with them, which is the
question a later phase will actually arrive with.

Two measurements decide it, both recorded in
[`docs/research/phase_008_sources.md`](../research/phase_008_sources.md).

- **Arithmetic is not exact.** `Decimal` operations run under a thread-local
  context, and `Decimal('1E+30') + Decimal('1E-30')` returns `1E+30` — the addend
  is discarded and nothing is raised.
- **Comparison is exact.** Two thirty-one digit values compare correctly under a
  context whose precision is three. Ordering consults the context only to decide
  whether to raise `InvalidOperation` on a `NaN`, and ADR-0030 refuses non-finite
  amounts at construction.

There is also a difference the type system already handles and one it cannot.
mypy refuses `Price < Quantity` statically. It cannot refuse
`price_in_usdt < price_in_eur`, because both operands are `Price`.

## Decision

**1. No arithmetic operator is defined.** Not `+`, `-`, `*`, `/`, `//`, `%` or
`**`, and not `__neg__`, `__abs__`, `__float__`, `__int__` or `__round__`.
Invariant 22 forbids silent data loss and invariant 17 assigns the precision
policy to Phase 010, so this module cannot define `+` without either choosing a
rounding mode that is not its choice or shipping an operation that loses data
without saying so.

**2. Ordering and equality are defined.** Comparison is exact and therefore
settles nothing Phase 010 owns. `Price` and `Quantity` implement `__lt__`,
`__le__`, `__gt__` and `__ge__` explicitly rather than through
`functools.total_ordering`, so that each appears in a stack trace and each has the
same failure mode on a unit mismatch.

**3. A wrong type returns `NotImplemented`; a wrong unit raises
`ValidationError`.** `NotImplemented` keeps the reflected-operand protocol
working and lets the interpreter write a message naming both classes, which is
adequate because mypy already refuses that call. A unit mismatch is not that: the
types match, mypy could not have refused it, and Python's own message would say
only that `<` is unsupported between two `Price` instances. `ValidationError` is
the category for "the caller must send different input"
([ADR-0022](0022-error-taxonomy-rooted-in-one-type.md)), and its message names
both denominations.

**4. `__eq__` never raises.** Equality is called by `in`, by `dict`, by `set` and
by every assertion, so one that raised would make these types unusable as keys
and turn a membership test into an exception. Two prices of different markets are
not the same value, and `False` says so. Ordering carries no such obligation.

**5. `__float__` and `__int__` are absent deliberately.** Defining either would
let `math.*` and any numeric helper reintroduce binary floating point behind
invariant 17's back, at a call site that would look entirely ordinary.

## Consequences

A caller who needs to add two amounts cannot, until Phase 010 says how. That is
the intended cost, and it is visible rather than silent: the operation raises
`TypeError` at the call site instead of rounding somewhere downstream.

The `NotImplemented`-versus-raise split has to be understood by anyone adding a
sixth value type, or the two halves of the rule will diverge. It is stated in
`docs/VALUE_TYPES_POLICY.md`, and the operation matrix there is executed by
`tests/contract/test_values_contract.py` rather than compared as text, so a row
claiming an operation works is a row that has been run.

Mutation testing found the first version of the cross-type test accepting a
degraded message: a comparison that reached the amount and compared it against
`None` raises `TypeError` too, with the same opening words. The assertion now
requires both class names to appear, which is what decision 3 actually promises.

## Alternatives Considered

**Define arithmetic inside `localcontext()` with `Inexact` trapped.** The
operation would either return the exact result or refuse, which pre-empts nothing
Phase 010 decides and would let that phase relax rather than replace. Refused on
three grounds: nothing consumes these types yet, so the operations would ship
against no real use; `localcontext` mutates thread-local state inside a domain
method; and the phase reads more honestly as "types, then arithmetic" than as
"types plus an arithmetic policy Phase 010 has not written".

**Raise from `__eq__` on a unit mismatch, for symmetry with ordering.** It would
make the rule uniform and the types unusable — see decision 4.

**Return `NotImplemented` for a unit mismatch as well.** Uniform, and it produces
a message about two `Price` instances that tells the caller nothing about which
two markets.

**`functools.total_ordering`.** Fewer lines. It derives `__le__` from `__eq__` and
`__lt__`, so the two operators would fail differently on a mismatch, which is the
opposite of what decision 3 is for.

## Risks and Trade-offs

The characteristic failure is that the absence of arithmetic becomes intolerable
before Phase 010 arrives, and somebody adds `+` to an adapter or a helper instead
of to this module — reintroducing the ambient rounding one layer out, where no
test is looking. The observable signal is a function that takes `.amount` from
two values and returns a `Decimal`.

The second risk is that decision 3 reads as an inconsistency rather than a rule.
If a later contributor "fixes" the asymmetry in either direction, the policy
document's operation matrix fails, which is the intended enforcement.

## References

- [`docs/VALUE_TYPES_POLICY.md`](../VALUE_TYPES_POLICY.md)
- [`docs/research/phase_008_sources.md`](../research/phase_008_sources.md)
- [`docs/engineering/ENGINEERING_CONTRACT.md`](../engineering/ENGINEERING_CONTRACT.md), invariants 17 and 22
- [ADR-0022](0022-error-taxonomy-rooted-in-one-type.md)
- [ADR-0030](0030-domain-values-are-denominated-wrappers-over-decimal.md)

## Supersedes

None.

## Superseded By

[ADR-0037](0037-arithmetic-is-exact-or-refused-under-an-explicit-context.md).

Phase 010 owns the precision policy this record deferred to by name, and it
reached the opposite conclusion on the central question: arithmetic *is*
defined, because a `decimal.Context` method performs it without touching the
thread-local context this record assumed it would have to mutate. The
reasoning below about *operators* remains accurate; the conclusion drawn from
it no longer describes the code.
