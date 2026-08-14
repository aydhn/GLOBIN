# ADR-0022 — One error root, five categories chosen by who must act, and no builtin inheritance

## Status

Accepted — Phase 005.

**Date:** 2026-08-14

## Context

Until this phase GLOBIN raised only standard library exceptions. `ValueError`
carried every rejection in `globin.adapters.architecture` — a missing table, a
wrong type, an unknown layer, a relative import — and `KeyError` carried one case
in `globin.domain.architecture`. That was deliberate rather than neglectful: the
adapter's docstring said so, on the grounds that one ad-hoc scheme is cheaper to
replace than two competing ones, and
[`ENGINEERING_CONTRACT.md`](../engineering/ENGINEERING_CONTRACT.md) invariant 9
forbade inventing a hierarchy before the phase that owned it.

The scheme had reached its limit. A caller could not distinguish a malformed
configuration file from a caller passing a bad argument, and neither from
`ValueError` raised by the standard library inside the same call. Every later
band makes that worse: Phases 033-048 add a transport that fails in ways
distinct from the venue refusing, and `MEMORY.md` records as an architectural
invariant that a timeout or 5XX does not prove an order failed. A system that
cannot tell "no answer" from "answered no" cannot honour that.

The design question was not whether to have a hierarchy but what axis to divide
it on, because the wrong axis is worse than none.

## Decision

**1. One root.** Every fault GLOBIN raises deliberately descends from
`GlobinError`, so `except GlobinError` catches all of them and nothing else.

**2. Five categories, divided by who must act**, not by where the `raise`
appears: `ConfigurationError` (the operator edits a file), `ValidationError` (the
caller sends different input), `TransportError` (the request never arrived or
never came back), `ExchangeError` (the venue answered and refused) and
`InternalError` (a GLOBIN invariant broke; always a defect).

A hierarchy named after subsystems is the alternative everyone reaches for. It
grows one class per module, tells a reader nothing the traceback did not, and
leaves unanswered the only question a caller has at the `except`: *can I proceed,
retry, or must a human change something?* Naming the responsible party answers it
at the point of catching.

**3. Nothing inherits a builtin exception type.** `ValidationError` is not a
`ValueError`. The migration would have been smoother if it were, and the cost is
that every unrelated `except ValueError` in the codebase would start catching
GLOBIN faults it knows nothing about — reintroducing the ambiguity the hierarchy
exists to remove.

**4. A `FaultDomain` `StrEnum` names the categories**, and each class declares
exactly one. This is what makes the separation assertable: a contract test
requires the direct subclasses of `GlobinError` and the members of `FaultDomain`
to correspond one-to-one in both directions, so a sixth category cannot be added
by subclassing and a declared category cannot go unimplemented. The root
deliberately declares no domain, so `raise GlobinError(...)` produces an object
with no category and is visibly wrong.

**5. The module sits above the layer stack**, registered in the `[shared]` table
of [`dependency-rules.toml`](../architecture/dependency-rules.toml) beside
`globin.project_contract` and `globin.roadmap`. It is not in `globin.domain`:
`ConfigurationError` and `TransportError` are infrastructure vocabulary, and a
domain layer that names them has had adapter concerns pushed into it. Like the
other shared modules it must import no layer, which the architecture suite
checks.

**6. This does not decide retryability.** No `retryable` flag hangs off
`TransportError`. Whether a timed-out request may be replayed depends on whether
it was idempotent, which is Phase 083's question, and on the reconciliation
Phase 086 owns. A boolean added here would be guessed, and it would be believed.

**7. Existing raises are migrated, not wrapped.** The adapter's validators raise
`ConfigurationError`; the relative-import rejection raises `ValidationError`;
`band_for_phase` raises `ValidationError` and `policy_for` raises
`InternalError`. `tomllib.TOMLDecodeError` is left alone — a file that is not
valid TOML is a broken file rather than a wrong contract, and `tomllib` already
reports the line and column.

## Consequences

- `except ValueError` no longer catches GLOBIN's rejections. Any code written
  against the old behaviour breaks loudly, which is the intended outcome and the
  reason the migration happened in one phase rather than gradually.
- Two `# noqa: TRY004` suppressions disappeared rather than being reworded. The
  rule asks for `TypeError` after an `isinstance` check; raising a domain-named
  error satisfies it outright. A standing exception left
  [`STATIC_ANALYSIS.md`](../engineering/STATIC_ANALYSIS.md), which is the rarer
  direction for that list to move.
- `TransportError` and `ExchangeError` have no callers until Phases 033-048. They
  are complete classes rather than stubs, and the contract test holds them to the
  same rules as the three in use, but a reader will meet two categories nothing
  yet raises.
- Adding a sixth category now costs an enum member, a class and a passing
  contract test. That is friction by design: the axis is the decision, and a
  category that does not fit "who must act" is a sign the axis is being eroded.
- `globin.errors` is importable from every layer, which makes it the second place
  after `project_contract` where a later phase could smuggle shared state. The
  architecture suite's shared-module rule is the only thing preventing that.

## Alternatives Considered

**Subclass the builtins as well** — `class ValidationError(GlobinError,
ValueError)`. Rejected. It preserves every existing `except ValueError` for free,
and that is precisely the problem: a handler written to catch a bad `int()`
conversion would silently absorb a GLOBIN validation fault, and the taxonomy
would exist while changing nothing about what code actually catches.

**Divide by layer** — `DomainError`, `AdapterError`, `RuntimeError`. Rejected. It
is mechanical to apply and useless to a caller, who knows what they called and
wants to know what to do. It also grows without bound: every new package invites
a new class.

**Divide by recoverability** — `RecoverableError` and `FatalError`. Rejected as
premature and probably wrong. Recoverability is a property of the operation and
its idempotency, not of the fault, and Phases 083 and 086 own that reasoning.
Encoding a guess as a class hierarchy would make it very hard to revise.

**A single `GlobinError` with a `domain` field and no subclasses.** Rejected.
Catching then requires `except GlobinError` plus an `if` on the field, which
cannot be checked by a type checker and reads as an afterthought at every call
site. The subclass tree makes the categories usable by the language rather than
by convention.

**Put the module in `globin.domain`.** Rejected on the boundary. Every layer may
import `domain`, so it would have worked, and it would have meant the innermost
layer defining `TransportError` — outward vocabulary in the one place
[`ARCHITECTURE_PRINCIPLES.md`](../ARCHITECTURE_PRINCIPLES.md) says must be
describable without mentioning HTTP or any venue.

## Risks and Trade-offs

The characteristic failure mode of a "who must act" axis is that some faults have
two answers. A malformed response from the exchange is arguably an
`ExchangeError` (the venue sent it) and arguably a `ValidationError` (GLOBIN
refused to parse it). This record does not resolve that case, because there is no
code that produces it yet, and resolving it in the abstract would produce a rule
written without evidence. Phases 033-048 will have to.

The observable signal that the axis has eroded is a class whose name answers
"where" rather than "who" — or, more insidiously, a category being chosen at a
`raise` site by which one is nearest in the file. The contract test catches the
first and cannot catch the second; only review can.

A weaker point worth recording: `TransportError` and `ExchangeError` are designed
against documentation rather than experience, because GLOBIN has never made a
request. If Phases 033-048 find the split unworkable, the right response is a
superseding ADR rather than quietly widening one of them.

## References

- [`../../ROADMAP.md`](../../ROADMAP.md) — Phase 005's purpose, which names the
  five categories.
- [ADR-0021](0021-phase-005-widens-to-include-the-test-foundation.md) — why this
  phase delivered the taxonomy alongside the test foundation.
- [ADR-0014](0014-layered-ports-and-adapters-and-inward-dependencies.md) — the
  layer contract that places this module above the stack.
- [`../engineering/ENGINEERING_CONTRACT.md`](../engineering/ENGINEERING_CONTRACT.md)
  — invariants 9 and 23, on structured errors and never swallowing them.
- [`../engineering/STATIC_ANALYSIS.md`](../engineering/STATIC_ANALYSIS.md) — the
  `TRY004` exception this decision removed.

## Supersedes

None.

## Superseded By

None.
