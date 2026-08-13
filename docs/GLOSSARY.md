# Glossary

Shared vocabulary for GLOBIN. Terms in this project mean exactly one thing;
where an industry term is ambiguous, the definition here is authoritative.

Entries marked **⚠ commonly confused** name a distinction that has real
consequences if collapsed.

---

## Environments

**Production** — Binance's live infrastructure with real funds and real orders.

**Testnet** — ⚠ commonly confused. *Separate* Binance infrastructure with its
own base URLs and its own credentials. Funds are virtual. Spot Testnet resets
roughly monthly without notice and serves only `/api` endpoints, so `/sapi`
functionality such as Margin and Wallet is unavailable there. Futures Testnet is
a different environment again.

**Demo Mode** — ⚠ commonly confused. Virtual balances on *production*
infrastructure, with keys issued through a separate demo portal. Documented for
Spot only. It is **not** a synonym for testnet: different infrastructure,
different credentials, different coverage.

**Internal simulation** — GLOBIN's own simulated execution, used where no
Binance non-production environment exists for a product. Entirely local.

**Paper trading** — a *composition* of the above chosen per product, not a
global switch. Some products may run against demo, others against testnet,
others against internal simulation, within a single paper session.

**Capability matrix** — the authoritative mapping of which product supports
which environment, with base URLs, credential scope and available endpoint
subset. An unmapped combination is refused, never downgraded. See
[ADR-0006](adr/0006-product-and-environment-capability-matrix.md).

---

## Products

**Spot** — direct asset exchange, no leverage.

**Cross Margin** — borrowed funds with margin shared across the account.

**Isolated Margin** — borrowed funds with margin confined to a single pair, so
liquidation there cannot consume unrelated collateral.

**USDⓈ-M Futures** — futures margined and settled in stablecoin.

**COIN-M Futures** — futures margined and settled in the base cryptocurrency,
with contract multipliers and delivery semantics that differ from USDⓈ-M.

**Options** — contracts conveying a right rather than an obligation.

**Portfolio Margin** — unified margin computed across products rather than
per-product.

**Product family** — a Binance surface with its own endpoints, semantics,
limits and environment coverage. Binance publishes a separate SDK package per
family, and GLOBIN mirrors that separation.

---

## Execution

**Order state machine** — the explicit set of order states and legal
transitions, including indeterminate states.

**Indeterminate state** — ⚠ commonly confused. An order whose outcome is
genuinely unknown, typically after a timeout or 5XX response. Binance documents
that such a response does **not** mean failure. Treating it as failure produces
duplicate positions; treating it as success produces phantom ones. Only querying
authoritative state resolves it.

**Idempotency key** — a deterministic client order identifier making a retry
safe, because the exchange can recognise the resubmission.

**Reconciliation** — continuously comparing local state against authoritative
exchange state and repairing divergence. Not an error path; a permanent
background responsibility.

**Pre-trade risk gate** — the mandatory, unbypassable check every order passes
immediately before submission. Positioned last so that a defect anywhere
upstream still cannot breach a ceiling.

---

## Research

**Point-in-time correctness** — the guarantee that research sees only what was
knowable at the moment being simulated.

**Lookahead / leakage** — ⚠ commonly confused with ordinary overfitting.
Information from the future reaching a model or backtest. Uniquely dangerous
because it *improves* apparent results, so it is indistinguishable from success
until real capital is committed. Overfitting, by contrast, usually shows up as
poor out-of-sample performance.

**Purging and embargo** — removing training samples whose label windows overlap
the validation period, and imposing a gap after it, so overlapping labels cannot
leak across folds.

**Walk-forward** — repeatedly training on past data and evaluating on the
immediately following unseen period. The primary honesty test for a time-series
strategy.

**Out-of-sample holdout** — data reserved from all development, consulted rarely
and under governance, because each consultation partly spends it.

**Evidence gate** — a machine-checkable condition a candidate must satisfy
before influencing live trading. Gates cannot be weakened by the system itself.

**Champion / challenger** — the incumbent in use, and a candidate evaluated
against it on identical terms.

**Shadow mode** — generating real decisions without sending orders, to compare
intent against reality without risking capital.

**Probabilistic edge** — the only claim GLOBIN makes about performance: a
measurable statistical advantage after realistic costs and out-of-sample
validation. Never a guarantee.

---

## Risk

**Immutable ceiling** — ⚠ commonly confused with a configured limit. An absolute
bound that no strategy, model, optimiser or autonomous process may raise. Only
the human owner can change it, by editing source and committing. See
[ADR-0008](adr/0008-immutable-upper-risk-constraints.md).

**Policy limit** — a bound changeable through governed process with evidence.

**Tunable parameter** — a value optimisation is permitted to search.

**Kill switch** — the operator-triggered emergency stop that halts trading and
can flatten exposure.

**Circuit breaker** — an automatic halt triggered by drawdown or anomaly
thresholds, without human involvement.

---

## Programme

**Phase** — one of the 320 numbered units of work. Implemented in order;
implementing ahead is a defect.

**Band** — one of twenty contiguous groups of sixteen phases. Boundaries are
immutable.

**Phase gate review** — the final phase of each band, reconciling inconsistency
before the next band builds on top of it.

**Contract test** — a test asserting a project rule rather than behaviour, so
that policy is enforced rather than merely documented.

---

## Architecture

Full descriptions live in [`architecture/README.md`](architecture/README.md);
these are the one-line definitions.

**Layer** — one of the five ordered divisions of the `globin` package: domain,
ports, application, adapters, runtime. Which may import which is fixed by
[`architecture/dependency-rules.toml`](architecture/dependency-rules.toml).

**Domain** — the innermost layer. Pure concepts, values and rules, describable
without naming any technology.

**Port** — an abstract contract saying what the core needs from the outside
world, without saying who provides it. Declared as a `typing.Protocol`.

**Adapter** — a concrete implementation of a port. The only layer permitted to
touch the filesystem, the network or the environment.

**Composition root** — the single place, `globin.runtime`, where concrete
implementations are chosen and objects are wired together.

**Inward dependency** — a dependency from an outer layer on an inner one. The
only permitted direction; the reverse is a layering violation.

**Modular monolith** ⚠ *commonly confused* — one repository, one distribution
and one process, with boundaries enforced between packages rather than across a
network. Not a microservice system, and not an unstructured one.

**Container** ⚠ *commonly confused* — in the C4 model, an application or data
store that must be running or must exist for the system to work. **Not** a
Docker container; GLOBIN uses no containerisation.

**Import-time side effect** — work performed merely by importing a module.
Prohibited in every layer: importing must declare, never act.
