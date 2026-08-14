# ADR-0039 — Identifiers register kinds, not instances, and the registry is a function

## Status

Accepted — Phase 011.

**Date:** 2026-08-15

## Context

`ROADMAP.md` assigns Phase 011 to *Identifier and Naming Registry*: "define
canonical identifiers for symbols, products, environments, runs, models and
orders across the system". Four documents already defer to it by name —
`VALUE_TYPES_POLICY.md` for "canonical identifiers, and the register of assets
that exist", `TIME_POLICY.md` for runs and orders, `PRECISION_POLICY.md` for
markets and assets, and `GLOSSARY.md` for the register of canonical identifiers.

The word *registry* carries two readings, and they lead to different systems.

A registry of **kinds** answers "what forms may a product identifier take". A
registry of **instances** answers "which products exist". The second is the
reading a reader arrives with, because that is what the word usually means, and
it is the one this phase must refuse.

Phase 008 already settled the equivalent question one layer down and left the
argument in place. `Currency` validates the shape of a code and nothing else;
`Currency("ZZZQ")` succeeds; and `tests/unit/test_values.py` carries
`test_a_well_formed_code_no_venue_lists_is_still_a_currency`, whose docstring
reads "If somebody adds a set of known codes to the domain layer, **this fails**
— which is the only way the absence of a thing can be enforced." The reason is
ADR-0006: which assets a venue lists is a capability question answered against
the venue, and it changes without GLOBIN being redeployed.

The same reasoning applies to products and environments, and the programme
already schedules the work: Phase 033 inventories the product families, Phase
035 models the environment classes, Phase 036 builds the capability matrix, and
Phases 049-050 build the instrument register. A tuple of product names written
here would displace four phases and be wrong quietly in between.

A second question arrived with the implementation. The natural expression of a
registry is a module-level table, and `tests/architecture/test_architecture_contract.py`
forbids it: a layer package may perform no call while being imported, and
building a specification object is a call. The existing precedents are
`precision._exact_context` and `clock._epoch`, both functions for the same
reason.

## Decision

**1. The registry holds kinds. It never holds instances.**
`IdentifierKind` enumerates the six the roadmap names, and `specification(kind)`
returns the canonical form of each: an alphabet, a length range and a one-line
summary. No list of products, environments, assets or markets appears anywhere
under `src/globin/domain/`.

**2. The registry is load-bearing, not descriptive.** Every identifier type
validates itself by calling `specification`. A registry that described the types
alongside them would be a second copy of the rules, free to drift from the
first — the failure `docs/engineering/SOURCE_OF_TRUTH.md` names. There is
nothing here to drift, because the description is the implementation.

**3. The registry is a function, not a constant.** `specifications()` builds the
tuple when called. This is the import-time-work rule, not a preference.

**4. The `SYMBOL` form is derived from Phase 008, not restated.** Its alphabet
and bounds are arithmetic on `CURRENCY_ALPHABET`, `SYMBOL_SEPARATOR` and the
currency length bounds. Widening a currency code widens this automatically, so
no tripwire comparing the two is needed — the copy that would need one does not
exist. `Symbol` gains no new type and `globin.domain.values` is unchanged by
this phase.

**5. Five kinds get a type of their own.** `ProductId`, `EnvironmentId`,
`RunId`, `ModelId` and `OrderId` are separate frozen dataclasses rather than one
type carrying a `kind` field, so that a product identifier cannot be passed
where an environment identifier belongs. A dataclass `__eq__` returns
`NotImplemented` across classes, so `ProductId("spot") == EnvironmentId("spot")`
is `False` with no code in either class saying so.

**6. Minting lives in the adapters layer.** `new_run_id` is the only generator
in GLOBIN, and it sits beside the clock for the reason ADR-0026 gives about
correlation identifiers: generation reads a source of randomness. Only runs are
minted, because runs are the only kind GLOBIN originates today.

**7. Two rules are enforced against the source tree.**
`tests/architecture/test_identifier_discipline.py` fails if venue vocabulary
appears as a live constant under `src/globin/domain/` — docstrings excluded, so
prose may name what code may not — and fails if any module there reads a source
of randomness. The second closes a real gap: `uuid`, `random` and `secrets` are
absent from the I/O-capable list in `dependency-rules.toml`, so nothing else
would have noticed.

## Consequences

`product_id("nosuchproduct")` succeeds, and a reader who expected the registry
to know which products exist will be surprised once. `IDENTIFIER_POLICY.md`
answers that surprise in its own section rather than leaving it to be inferred.

Phases 033, 035, 036 and 049-050 inherit a form to fill rather than a form to
invent, and inherit nothing they must first undo.

`ProductId`, `EnvironmentId` and `ModelId` share one specification today, so the
registry looks partly redundant. That is honest rather than accidental: they are
three different facts that currently take the same shape, and the entry that
distinguishes them is the summary a reader looks up. Collapsing them into one
kind would have to be undone the first time one diverges.

Five near-identical classes is real repetition. The alternative was one class
and a rule that every comparison also compares the kind, which is repetition
moved to every call site instead of concentrated in one file.

## Alternatives Considered

**One `Identifier` type with a `kind` field.** Fewer classes, and a registry that
maps kind to specification without five constructors reading it. Rejected
because equality is the operation identifiers exist for: a single type compares
`spot` the product equal to `spot` the environment unless every call site
remembers to compare the kind too, and the call site that forgets is the one
that groups a report.

**Enumerate the products and environments now,** taking the names from
`GLOSSARY.md`. Tempting, because the names are already written down and the
roadmap line says "define canonical identifiers for ... products, environments".
Rejected because it reads *identifier* as *instance*: it would displace Phases
033 and 035, and it would compile into the innermost layer a fact that changes
without a deployment. The audit that prompted this record also found the
existing lists disagreeing with each other — `GLOSSARY.md`, `PROJECT_CHARTER.md`
and `docs/research/phase_001_sources.md` name different sets — which is
precisely the reconciliation Phase 033 exists to do against primary
documentation.

**Give `Symbol` a `from_venue` classmethod** so the registry could decode
`BTCUSDT`. Rejected as scope leakage. Decoding requires knowing which assets a
venue quotes in — `BTCUSDT` splits as `BTC`/`USDT` or `BTCU`/`SDT` — so it is
not a naming decision at all. ADR-0030 already assigns it to Phases 033-048.

**Put the specifications in a module-level tuple** and accept the import-time
call. Rejected: the rule it breaks is enforced, and the exemption would be the
first. A function costs one pair of parentheses.

**Mint every kind, not only runs.** An `new_order_id` would be usable the moment
Phases 081-096 arrive. Rejected because nothing can yet say what a venue will
accept, so the generator would encode a guess that later code would trust.

## Risks and Trade-offs

The characteristic failure is a register arriving by increments: not a tuple of
product names, but a default argument, a lookup table for rendering, or a test
fixture promoted into the module. The observable signal is any venue vocabulary
appearing as a live constant in the domain layer, which is why that is the check
rather than a review habit. It is a proxy and an alias defeats it, in the sense
`dependency-rules.toml` already uses about I/O imports.

The second risk is that the denylist ages. It names the products and
environments known in Phase 011, so a family Binance introduces later is
invisible to it until somebody adds the word. Phase 033 is where that list is
established against primary documentation, and it is the phase that should
widen this check.

The third is that `OPAQUE_ALPHABET` turns out to be wider than a venue accepts.
That is expected: it bounds GLOBIN's own shape and makes no claim about Binance,
and Phases 033-048 will record the narrower rule against the venue rather than
narrowing this one.

## References

- [`ROADMAP.md`](../../ROADMAP.md)
- [`docs/IDENTIFIER_POLICY.md`](../IDENTIFIER_POLICY.md)
- [`docs/research/phase_011_sources.md`](../research/phase_011_sources.md)
- [`docs/architecture/dependency-rules.toml`](../architecture/dependency-rules.toml)
- [ADR-0006](0006-product-and-environment-capability-matrix.md), which makes
  which-products-exist a capability question
- [ADR-0022](0022-error-taxonomy-rooted-in-one-type.md)
- [ADR-0026](0026-correlation-is-bound-explicitly-not-ambiently.md), which places
  generation in the adapters layer
- [ADR-0030](0030-domain-values-are-denominated-wrappers-over-decimal.md), which
  assigns the concatenated venue spelling to Phases 033-048

## Supersedes

None.

## Superseded By

None.
