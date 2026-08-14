# Engineering Contract

The invariants every line of GLOBIN code must satisfy, for the whole programme.

This is the most stable document in the repository. Phases come and go; these do
not. A change that violates one of them is a defect even when it passes review,
passes its tests, and does what its author intended.

---

## How to read this

**None of these are implemented in Phase 2.** This document was written before
almost all of the code it governs, deliberately: an invariant agreed after the
code exists is a negotiation, and the code usually wins. Agreed first, it is a
constraint.

Six invariants below are **owned elsewhere**. They are stated here in one line
with a link, never restated in full, because a rule written in two places
eventually says two different things — see
[`SOURCE_OF_TRUTH.md`](SOURCE_OF_TRUTH.md).

Where an invariant says *"where it matters"* or *"where applicable"*, that
qualifier is load-bearing. Applying every rule everywhere produces ceremony, and
ceremony is what people learn to skip.

---

## Disposition

### 1. Correctness over convenience

When a correct implementation is harder than a convenient one, write the correct
one. This system moves money without supervision. The convenient version is
usually convenient because it assumes something that is only *usually* true, and
the cost of "usually" is paid at the worst possible moment.

### 2. Fail closed

On ambiguity, refuse. Never guess, never fall back to a permissive default, never
downgrade an unmapped configuration to a working one. A refusal is visible and
recoverable; a silent substitution is neither.

### 3. Determinism

Given the same inputs, the same code must produce the same outputs. Randomness is
permitted only with an explicit, recorded seed. Iteration order, dictionary
ordering and set ordering must never affect a result that is compared, stored or
traded on.

### 22. No silent data loss

Discarding data is an explicit, logged decision, never a side effect. Overwriting
a file, truncating a series, dropping rows during a merge, or narrowing a numeric
type all count as discarding data.

### 23. No silent exception swallowing

`except: pass` is prohibited. So is catching a broad exception and continuing as
though nothing happened. An exception is either handled — meaning the failure is
resolved and that is explainable — or it propagates. "Logged and ignored" is
swallowing with extra steps.

### 9. Structured error handling

Errors carry structure, not just prose: what failed, which operation, whether a
retry is safe. The project-wide exception hierarchy lives in
[`globin.errors`](../../src/globin/errors.py), designed in Phase 005: one root,
and five categories divided by **who must act** — configuration, validation,
transport, exchange and internal. Every fault GLOBIN raises deliberately
descends from `GlobinError`, and nothing in the tree inherits a builtin
exception type.

Do not introduce a competing scheme, and do not add a sixth category without the
argument that goes with it — the axis is the decision, and
[ADR-0022](../adr/0022-error-taxonomy-rooted-in-one-type.md) records why it is
"who must act" rather than "where it was raised". Whether a fault is retryable is
deliberately not modelled; that depends on idempotency (Phase 083) and
reconciliation (Phase 086), not on the exception's class.

---

## Predictability

### 6. Idempotency where applicable

Any operation that can be retried must be safe to retry. This matters most at the
exchange boundary, where a timeout does not tell you whether the operation
happened — see *A failed request does not prove a failed operation* in
[`ARCHITECTURE_PRINCIPLES.md`](../ARCHITECTURE_PRINCIPLES.md).

### 12. Reproducibility

A result that cannot be reproduced is an anecdote. Research output — a backtest,
a training run, an optimisation study — must record the inputs, code version,
configuration and seeds needed to produce it again.

### 25. Time is explicit and timezone-aware

Timezone-naive datetimes must not cross a domain boundary. Internal time is UTC.
Wall-clock time is an input to be injected, never read ambiently by code that
needs to be testable. The full clock discipline is **Phase 009**.

### 4. Explicit configuration

Behaviour comes from configuration that is declared, validated and visible.
Nothing important is decided by an environment variable read at an arbitrary
depth of the call stack, and nothing important is hard-coded where it cannot be
seen. The typed configuration model is
[`globin.domain.configuration`](../../src/globin/domain/configuration.py), and
what may be configured is registered in
[`../CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md). A setting that is not
in that register is refused by name rather than ignored. Which files and
environment variables feed it remains **Phases 026-027**.

### 5. No hidden global state

Module-level mutable state, singletons and import-time caches make behaviour
depend on history and on import order. Where shared state is genuinely required,
it is passed explicitly. Import must not perform I/O, open connections, read
configuration or start work.

Since Phase 003 this is checked rather than trusted: dependencies are wired in a
single composition root and the syntax tree of every layer module is inspected
for work that would run at import
([ADR-0015](../adr/0015-single-composition-root-and-no-import-time-side-effects.md)).

---

## Structure

### 7. Domain separated from adapters

The core — instruments, orders, positions, risk, signals — must not know that
Binance exists. Exchange access lives behind adapters. This is what makes the
domain testable without a network and what stops a vendor change from becoming a
rewrite. It is not multi-exchange support, which is an explicit non-goal
([ADR-0002](../adr/0002-binance-global-only-exchange-scope.md)).

The layers this separation is expressed in, and their responsibilities, are
described in [`../architecture/README.md`](../architecture/README.md).

### 19. Dependency direction

Dependencies point inward: adapters depend on the domain, never the reverse. A
domain module importing an HTTP client, a database driver or a vendor SDK is a
layering violation regardless of how convenient it is.

Which layers exist and which may import which is declared in
[`../architecture/dependency-rules.toml`](../architecture/dependency-rules.toml)
and enforced by test
([ADR-0014](../adr/0014-layered-ports-and-adapters-and-inward-dependencies.md)).
That file is the canonical matrix; this invariant states the principle and does
not restate the rules.

### 8. Typed boundaries

Every public function, method and module boundary is annotated. `mypy` runs in
strict mode and must pass. Types at a boundary are a contract; types inside a
function are a convenience.

### 17. Financial arithmetic does not assume binary floating point is safe

Prices, quantities, balances and fees are values where representation error is a
correctness problem, not a rounding curiosity. Exchange-facing quantities must
respect tick and step sizes exactly. Where precision matters, use exact
arithmetic and say so; do not let a `float` reach a place where a cent can
disappear. The precision policy is **Phase 010**.

---

## Evidence

### 15. Capability is discovered, not assumed

Which products exist in which environments is verified against the venue, never
inferred. Owned by *Test environments are product-specific* in
[`ARCHITECTURE_PRINCIPLES.md`](../ARCHITECTURE_PRINCIPLES.md) and
[ADR-0006](../adr/0006-product-and-environment-capability-matrix.md).

### 16. External behaviour comes from current primary evidence

Endpoints, parameters, error codes, limits and library signatures are read from
official documentation and recorded, never guessed. Owned by
[`SOURCE_POLICY.md`](../SOURCE_POLICY.md) and
[ADR-0004](../adr/0004-official-apis-only-no-scraping.md).

### 13. Point-in-time correctness

No computation may use information that did not exist at the moment it claims to
model. Owned by *Point-in-time correctness is structural* in
[`ARCHITECTURE_PRINCIPLES.md`](../ARCHITECTURE_PRINCIPLES.md).

### 14. No look-ahead or leakage

Leakage is uniquely dangerous because it *improves* apparent results, so it must
be impossible by construction rather than caught by review. Owned by
[`ARCHITECTURE_PRINCIPLES.md`](../ARCHITECTURE_PRINCIPLES.md) and
[`TESTING_STRATEGY.md`](../TESTING_STRATEGY.md).

### 18. Live trading is opt-in behind gates

Paths that commit real capital default to off and open only through explicit
gates the system cannot weaken on its own. Owned by *Autonomy operates inside
fixed bounds* in [`ARCHITECTURE_PRINCIPLES.md`](../ARCHITECTURE_PRINCIPLES.md)
and [ADR-0008](../adr/0008-immutable-upper-risk-constraints.md).

---

## Operability

### 10. Observability without leaking secrets

The system must be explainable after the fact: what it decided, on what input,
and why. That obligation never justifies logging a credential. API keys,
signatures, tokens and private keys are redacted at the point of formatting, not
filtered downstream.

### 24. No secret material in logs, errors or telemetry

Stated separately from 10 because it is absolute. There is no severity level, no
debug flag and no local-only exception that permits writing a live credential to
an output stream. Secret handling policy is **Phase 015**.

### 11. Testability

Code is written so it can be tested without a network, without a real clock and
without live credentials. If a unit can only be exercised against the exchange,
it is built wrong. The levels, fixture scope rules and naming conventions live in
[`TESTING_STRATEGY.md`](../TESTING_STRATEGY.md); which checks are mandatory and
what a failure means is [`QUALITY_GATES.md`](QUALITY_GATES.md).

---

## Change

### 20. Backward compatibility and migration discipline

Persisted data outlives the code that wrote it. Breaking a stored format requires
a migration path and an explicit decision, not a silent schema change. In-repo
interfaces may change freely while the phase that owns them is active, but not
after a later phase depends on them. Serialization contracts are **Phase 012**.

### 21. Documentation evolves with the architecture

A phase whose documentation contradicts its code is incomplete. Owned by
[ADR-0010](../adr/0010-living-documentation-responsibilities.md); the mechanics
are in [`DOCUMENTATION_STANDARD.md`](DOCUMENTATION_STANDARD.md).

---

## When an invariant is genuinely wrong

Say so, in an ADR, with the reasoning. Do not resolve it by writing code that
quietly contradicts it — that leaves the repository asserting two incompatible
things with nothing recording which one won.

An invariant that has been consciously superseded is healthy. An invariant that
is merely ignored is how a codebase stops meaning what it says.
