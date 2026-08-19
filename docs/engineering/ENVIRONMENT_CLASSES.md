# Environment Classes

What an environment *is*, as opposed to what it is called — and why that turned
out to be the thing the signing layer needed most.

[`EnvironmentId`](../../src/globin/domain/identifiers.py) has said since Phase 011
that it names an environment and promises nothing about it: *"Naming an
environment is not classifying one. ADR-0006 refuses to treat 'not production' as
a single thing, and Phase 035 models the classes and their guarantees."* This is
that model.

---

## Why the registry could not do this

Phase 033's [API reality registry](BINANCE_API_REALITY.md) already classifies
environments. It records `production`, `demo` and `testnet` as distinct kinds
rather than as a boolean, with `semantics`, `carries_real_capital` and a
`host_marker` per product-and-environment pair. That was the seventeenth scope
amendment's work and it is correct.

It cannot answer this document's question, for a reason that is structural rather
than a matter of where to put a field:

> **GLOBIN's default profile is `paper`, and Binance publishes no `paper`.**

[`config/profiles/paper.toml`](../../config/profiles/paper.toml) describes
*"simulated execution against real market data"* — an environment GLOBIN itself
hosts, with no venue, no endpoint, no key, and no row a registry of venue facts
could hold. Inventing one would be recording a claim about Binance that Binance
does not make.

So there are two documents and they answer different questions. The registry says
what the venue documents. [`environment-classes.toml`](environment-classes.toml)
says what a class of environment *promises*, including the class the venue has
never heard of.

---

## The four classes

ROADMAP row 035 names exactly these: *production, testnet, demo and internal
simulation as distinct classes with distinct guarantees.* There is no fifth.

| | live_capital | venue_testnet | venue_demo | internal_simulation |
|---|---|---|---|---|
| `carries_real_capital` | **yes** | no | no | no |
| `reaches_venue` | yes | yes | yes | **no** |
| `accepts_credential` | yes | yes | yes | **no** |
| `orders_are_binding` | **yes** | no | no | no |
| `market_data_is_real` | yes | no | no | **yes** |
| `state_is_venue_owned` | yes | yes | yes | no |
| `feature_parity_with_live` | yes | **no** | yes | no |

### The names are GLOBIN's, not the venue's

`live_capital` rather than `production`, and `venue_testnet` rather than
`testnet`. That is not a preference:
[`test_identifier_discipline.py`](../../tests/architecture/test_identifier_discipline.py)
refuses a venue instance name anywhere in the domain layer, because *"a register
of instances belongs to the phase that reads it from the venue, not to the layer
that bounds its shape"*. The first draft of this model spelled the venue's own
names and the tripwire caught it.

[`ProductScope`](../../src/globin/domain/api_reality.py) set the precedent by
spelling `trading` and `supporting` rather than anything the venue calls itself.
The `venue_` prefix also carries meaning: it separates the two classes the venue
hosts from the one GLOBIN does.

### Two guarantees are not derivable from the others

**`market_data_is_real` is true for the live exchange *and* for internal
simulation**, and false for both venue sandboxes. That reads like an error until
both sources are read. Demo Mode's own document says *"Realistic market data is
not equal to 'real' market data"*; `paper.toml` says *"Simulated execution against
real market data"*.

So the simulated environment has **real prices and computed fills**, while demo
has **realistic prices and — to itself — real fills**. Collapsing the two into one
"is this real" axis would lose exactly the distinction a backtest's validity turns
on.

**`feature_parity_with_live` is why there are seven fields and not six.** The two
venue sandboxes agree on all six other guarantees. Without a seventh they would be
indistinguishable, and the roadmap row's *"distinct guarantees"* would be untrue
of half its classes. Demo Mode is documented as *"always has the same features as
the live exchange"*; the testnet is documented as having order books independent
of the live exchange, with new features appearing there first. A caller asking
*does behaviour here predict production* gets different answers, and
[a contract test](../../tests/contract/test_environment_class_contract.py) fails
if any two classes ever promise the same thing.

---

## What this buys the signing layer

`accepts_credential` is **gate 1** of
[`resolve_auth`](../../src/globin/application/auth.py) — checked before the
registry is consulted, before a credential is looked up, and before any signer is
chosen.

```console
$ globin auth capabilities --family spot --environment paper

  FAIL  environment_forbids_credential
        paper is classified internal_simulation, which reaches no venue; there is
        nothing to authenticate to, so no credential is read and nothing is signed
```

That is stronger than a refusal. Not *we checked and declined to use the
credential*, but **no credential was ever reached for** — asserted by a test whose
secret store raises if anything asks it for anything.

Without this model there is no type that can say so, and *"do not sign for
paper"* would be a rule somebody has to remember rather than a value a gate reads.

---

## An unclassified name is a refusal

`classify()` returns `None` for a name nobody has classified, and `None` becomes
`ENVIRONMENT_UNCLASSIFIED`.

```console
$ globin auth capabilities --family spot --environment staging

  FAIL  environment_unclassified
        'staging' has no declared environment class, so its guarantees are
        unknown; an unclassified environment is refused rather than assumed safe
```

Defaulting to the safest class would be defensible and would still be a guess, and
a guess about which environment this is is the one guess ADR-0006 forbids by name.

---

## The mapping is declared, and one row proves why

`[[member]]` maps a name to a class. It is a table rather than a rule, and a rule
would have missed this:

```toml
[[member]]
name = "production"   # what the venue calls it
class = "live_capital"

[[member]]
name = "live"         # what GLOBIN's own profile is called
class = "live_capital"
```

The venue calls its live environment `production`; GLOBIN's profile for reaching
it is `live`. No rule about spelling connects those two words. It was found by the
contract test that compares every configuration profile against this table, not by
design — `config/profiles/live.toml` had existed since Phase 026 and classified as
nothing, so `--profile live` would have been refused as unclassified. Fail-closed
and therefore safe, and wrong.

A heuristic such as *a name containing "test" is a testnet* would be a naming rule
deciding a security-relevant fact.
[`EnvironmentRecord`](../../src/globin/domain/api_reality.py) already learned that
lesson from the other direction: its `host_marker` exists so a live host filed
under a paper environment is refused **structurally** rather than by a rule about
spelling that somebody trusts.

---

## Where each half lives

| | Holds | May not hold |
|---|---|---|
| [`domain/environment_class.py`](../../src/globin/domain/environment_class.py) | The four kinds and their guarantees | Any environment **name** — the layer contract forbids it |
| [`environment-classes.toml`](environment-classes.toml) | The name-to-class mapping, and the source each guarantee was read from | Anything the package does not also carry |
| [`adapters/environment_class.py`](../../src/globin/adapters/environment_class.py) | The reader, and the comparison | Any decision — it reports disagreements rather than resolving them |

The guarantees are declared **twice**, and
[a contract test](../../tests/contract/test_environment_class_contract.py)
compares them. `SOURCE_OF_TRUTH.md` refuses a second copy of a rule *unless a test
compares the copies*, and what the second copy buys is provenance: a boolean in a
Python module is a value somebody typed, while the same boolean in the document
carries the source it was read from.

`internal_simulation` cites `globin-own` rather than a venue document, which is
not a venue source and is not pretending to be. A contract test asserts it is the
only class citing it, and that no venue-hosted class does.

---

## What is checked, in both directions

| Claim | Where |
|---|---|
| The document and the package agree on every guarantee | `disagreements()`, empty |
| Every class the package declares is in the document | reader refuses a missing one |
| Every class the document declares is a real one | reader refuses an unknown name |
| Every registry environment is classified | contract test |
| `carries_real_capital` agrees between the two documents | contract test |
| Every configuration profile names a class | contract test |
| **`internal_simulation` has no registry row and no endpoint** | contract test |
| No two classes promise the same thing | contract test |
| Exactly one class risks real capital | contract test |

The seventh is the one that earns the file. An environment GLOBIN simulates having
a venue endpoint would be a contradiction, and the failure would be silent:
`resolve()` would hand back a URL, `resolve_auth` would still refuse at gate 1, and
the two documents would disagree about whether a venue exists with nothing
reporting it.

---

## Reading it

```bash
.venv\Scripts\globin.exe auth classes
```

```bash
.venv\Scripts\globin.exe auth classes --json
```

Reaches nothing, reads two committed documents, and reports every disagreement
between them. Exit `14` if the document and the package disagree, `0` otherwise.

---

## What this is not

**Not a capability matrix.** Which product-and-environment pairs are usable is
Phase 036's, driven by the registry rather than by this.

**Not a runtime guard on trading.** `carries_real_capital` is recorded and read by
the authentication surface; nothing here stops an order, because nothing yet
places one. Phase 297 owns refusing a live start, and Phases 305-320 own the
staged activation gates.

**Not a profile system.** `config/profiles/` names *documents*, and
[`CONFIGURATION_LAYOUT.md`](CONFIGURATION_LAYOUT.md) is explicit that a profile
document is structurally incapable of asserting what an environment is. This
model is what a profile's name maps *into*.
