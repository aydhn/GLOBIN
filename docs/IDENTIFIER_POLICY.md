# Identifier policy

What the six kinds of identifier are, what canonical form each one takes, and
where that form is stated. The registry lives in
[`src/globin/domain/identifiers.py`](../src/globin/domain/identifiers.py); this
document is where a reader finds the rules without reading the code, and
[`tests/contract/test_identifier_contract.py`](../tests/contract/test_identifier_contract.py)
compares the two in both directions so that neither can drift.

Written for a contributor about to name something. If you are asking "may I
call it that", the answer is in [The rules, as constants](#the-rules-as-constants):
lowercase and dotted for a product, an environment or a model; mixed case for an
order; thirty-two hexadecimal characters for a run.

---

## Why a registry exists

A system that names the same thing two ways has two things. `spot` and `SPOT`
are one product spelled twice; `BTC/USDT` and `BTCUSDT` are one market spelled
twice. Grouping a report by either spelling gives an answer that is wrong in a
way that looks right, and nothing raises.

The answer is one canonical form per kind, stated once. `specification(kind)`
is that statement, and every type in the module validates itself by calling it.
A registry that merely described the types alongside them would be a second copy
of the rules, free to drift from the first — the failure
[`SOURCE_OF_TRUTH.md`](engineering/SOURCE_OF_TRUTH.md) names. Here the
description *is* the implementation.

---

## The kinds

Each kind's description below is the `summary` field of its specification, and
the contract test compares the two.

| Kind | Denotes | Carried by |
|---|---|---|
| `SYMBOL` | A market, rendered as base, separator and quote. | `Symbol` |
| `PRODUCT` | A venue surface with its own endpoints and limits. | `ProductId` |
| `ENVIRONMENT` | A deployment target a product may be reached through. | `EnvironmentId` |
| `RUN` | One execution of GLOBIN doing a piece of work. | `RunId` |
| `MODEL` | A trained artefact that produces predictions. | `ModelId` |
| `ORDER` | An instruction GLOBIN sends a venue. | `OrderId` |

`SYMBOL` has no type of its own. `Symbol` already is one, delivered by Phase 008,
and a second carrying the same fact would be the duplicate
[`DEFINITION_OF_DONE.md`](engineering/DEFINITION_OF_DONE.md) forbids. Its
specification is instead *derived* from that module's constants, so widening a
currency code widens this automatically and the two cannot disagree.

---

## The rules, as constants

Each is published by the module, so a test and this table can agree with the
implementation instead of quoting it.

| Constant | Value |
|---|---|
| `NAME_ALPHABET` | `abcdefghijklmnopqrstuvwxyz0123456789._` |
| `OPAQUE_ALPHABET` | `0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_` |
| `HEX_ALPHABET` | `0123456789abcdef` |
| `MIN_NAME_LENGTH` | `2` |
| `MAX_NAME_LENGTH` | `64` |
| `MIN_OPAQUE_LENGTH` | `4` |
| `MAX_OPAQUE_LENGTH` | `64` |
| `RUN_ID_LENGTH` | `32` |

### Lowercase dotted names

Products, environments and models are named by people and read by machines, so
they take the narrowest alphabet that still expresses a hierarchy: lowercase
letters, digits, a dot to separate levels and an underscore to join words within
one. Two to sixty-four characters, case exact.

Uppercase is refused rather than normalised, for the reason
[`VALUE_TYPES_POLICY.md`](VALUE_TYPES_POLICY.md) gives about currency codes: one
spelling means one thing to search a log for.

The alphabet is the same set of characters as the module-level
`EVENT_NAME_ALPHABET` in
[`src/globin/domain/observability.py`](../src/globin/domain/observability.py),
and the two are deliberately not shared. An event name and a product identifier
answer to different phases and may legitimately diverge; binding them together
now would let one phase's decision silently constrain another's. No test
compares them, because they are not required to agree.

### Opaque identifiers

An order identifier crosses into somebody else's system and comes back, so it
takes a wider alphabet and **case is significant**. Folding it would be GLOBIN
deciding that two distinct orders are one.

The permitted set is the unreserved characters of RFC 3986 minus the tilde and
the full stop: every member survives a URL path, a query string, a JSON string
and a Windows filename without escaping. Four to sixty-four characters.

What a venue will actually accept is narrower, and establishing it is
Phases 033-048. This is a bound on GLOBIN's own shape, not a claim about
Binance.

### Run identifiers

Exactly thirty-two lowercase hexadecimal characters, which is what
[`uuid.UUID.hex`](https://docs.python.org/3/library/uuid.html) produces. The
length is fixed rather than bounded because the kind has exactly one producer:
anything of another length did not come from `new_run_id` and is refused rather
than tolerated.

This is the same length `new_correlation_id` produces, and the alignment is
intended. A run and the log records made during it are the same kind of token,
so a reader comparing them is comparing like with like. They remain distinct
concepts: a correlation identifier ties together one piece of work
([ADR-0026](adr/0026-correlation-is-bound-explicitly-not-ambiently.md)), and a
run is the execution that work happened in.

**Minting lives in the adapters layer.** Generating an identifier reads a source
of randomness, and ADR-0026 puts that beside the clock rather than in the
domain, so that a value built from identical inputs compares equal.
[`src/globin/adapters/identifiers.py`](../src/globin/adapters/identifiers.py)
holds the only generator in GLOBIN, and
[`tests/architecture/test_identifier_discipline.py`](../tests/architecture/test_identifier_discipline.py)
fails if a second appears in the domain.

---

## Kinds are registered; instances are not

`product_id("nosuchproduct")` succeeds, for the same reason `Currency("ZZZQ")`
does. Which products a venue offers is a capability question answered against
the venue ([ADR-0006](adr/0006-product-and-environment-capability-matrix.md)),
and it changes without GLOBIN being redeployed. A list compiled into the
innermost layer cannot express that, and would be wrong quietly.

This module bounds **shape**. The gate that keeps it that way is
`test_the_domain_layer_names_no_product_environment_or_asset`, which fails if
any venue vocabulary appears as a live constant anywhere under
`src/globin/domain/`. Prose is unaffected: the check excludes docstrings, which
is why this policy may name the things the code may not.

---

## Which operations exist

`answers` means the operation returns a value rather than raising.

| Attempt | Outcome |
|---|---|
| `specification of every kind` | `answers` |
| `specification of an unregistered kind` | `InternalError` |
| `satisfies with text in the form` | `answers` |
| `satisfies with a non-string` | `answers` |
| `ProductId == ProductId, same text` | `answers` |
| `ProductId == EnvironmentId, same text` | `answers` |
| `ProductId < ProductId` | `TypeError` |
| `hash of a ProductId` | `answers` |
| `str of a ProductId` | `answers` |
| `ProductId spelled with uppercase` | `ValidationError` |
| `ProductId spelled with a hyphen` | `ValidationError` |
| `ProductId of one character` | `ValidationError` |
| `ProductId built from a non-string` | `ValidationError` |
| `OrderId spelled with mixed case` | `answers` |
| `OrderId spelled with a full stop` | `ValidationError` |
| `RunId of thirty-two lowercase hexadecimal characters` | `answers` |
| `RunId of the wrong length` | `ValidationError` |
| `RunId spelled with uppercase hexadecimal` | `ValidationError` |
| `a newly minted run identifier` | `answers` |

Two rules generate that table.

**Equality answers; ordering does not exist.** `__eq__` is called by `in`, by
`dict`, by `set` and by every assertion, so one that raised would make these
types unusable as keys. A product and an environment sharing text are simply not
the same value, and `False` says so. Ordering is absent for the reason
`Currency` has none: identifiers have no meaningful order, and defining an
alphabetical one invites a report sorted by it and called canonical.

**A wrong shape gives `ValidationError`; a missing rule gives `InternalError`.**
The caller of `product_id("SPOT")` can fix the problem by sending different
input, which is what
[ADR-0022](adr/0022-error-taxonomy-rooted-in-one-type.md) means by validation. A
kind with no specification cannot be fixed by any caller — it means the registry
was edited in half — so it is an internal fault.

---

## What this policy does not decide

Naming the owning phase is what stops a reader inferring an answer from the
absence of a rule.

| Question | Phase |
|---|---|
| The value types a price, quantity or market is carried in | 008, delivered — [`VALUE_TYPES_POLICY.md`](VALUE_TYPES_POLICY.md) |
| Serialization and schema evolution for persisted identifiers | 012 |
| Which product families Binance offers, and what each is called there | 033 |
| What an environment is, and what each class guarantees | 035 |
| Which product and environment pairs are usable | 036 |
| The venue spelling of a market, such as the concatenated form | 033-048 |
| Which instruments exist, and their metadata | 049-050 |
| How an order identifier is generated and reconciled with the venue | 081-096 |
| A model's version, its training data and its lineage | 097 and beyond |

Three are worth spelling out.

**Naming an environment is not classifying one.** ADR-0006 refuses to treat "not
production" as a single thing, and Phase 035 models the classes and their
guarantees. `EnvironmentId` carries a name and asserts nothing about what the
name promises.

**A `ModelId` carries no version.** A model without a version is the classic
reproducibility failure, and it is precisely because the answer matters that
this phase does not guess it. Giving the type a version field now would fix the
shape of something Phases 097 and beyond have to design.

**Nothing here places an order.** `OrderId` exists so that the execution phases
inherit a form rather than inventing one under deadline. GLOBIN does not trade,
does not connect to any exchange, and has no credentials — see
[`README.md`](../README.md).
