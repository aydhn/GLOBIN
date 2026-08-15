# Serialization policy

How GLOBIN writes a value down, and how it reads one back after the code that
wrote it has changed.

Owned by Phase 012. The code is [`src/globin/domain/serialization.py`](../src/globin/domain/serialization.py)
and [`src/globin/adapters/serialization.py`](../src/globin/adapters/serialization.py);
[`tests/contract/test_serialization_contract.py`](../tests/contract/test_serialization_contract.py)
holds this document to them. Where the two disagree the code wins
([`docs/engineering/SOURCE_OF_TRUTH.md`](engineering/SOURCE_OF_TRUTH.md)) and the
disagreement is a defect in this file.

---

## The problem this exists to solve

[`ENGINEERING_CONTRACT.md`](engineering/ENGINEERING_CONTRACT.md) invariant 20
states it: persisted data outlives the code that wrote it. A record written today
is read by code that has been changed many times since, and the only thing
between those two moments is an agreement about shape.

Two failures follow from having no such agreement, and both are silent.

A value is **narrowed on the way in** — a timestamp truncated, a magnitude routed
through a float — so what is read back is not what was written. Nothing raises,
because at each individual step nothing was wrong.

A record is **read at the wrong version** by code that recognises most of the
fields. The unrecognised one is ignored, and it was the one the newer writer
added because it mattered.

---

## The rule everything else follows from

**Serialization is exact, or it is refused.**

Deliberately the same sentence
[ADR-0037](adr/0037-arithmetic-is-exact-or-refused-under-an-explicit-context.md)
makes about arithmetic, for a different reason. A stored value is read back and
compared against itself, so a conversion that quietly discards a digit does not
merely lose precision — it breaks `decode(encode(x)) == x`, which is the property
that makes the record worth keeping.

Every encoder either produces a value that reads back identical, or raises. None
narrows.

### The case that shows what this costs

`Instant.epoch_millis` floors, and
[ADR-0035](adr/0035-milliseconds-are-a-floored-projection.md) is right that it
should: a wire timestamp that has drifted into the future is the one an exchange
rejects.

`encode_instant` nevertheless **refuses** an instant carrying sub-millisecond
precision instead of flooring it. A request and a record are different things. A
caller who wants the floor writes `instant.epoch_millis`, which is one line and
says so.

---

## The envelope

Every persisted document carries two keys, flat at the top level beside the
payload's own fields:

| Key | Type | Meaning |
|---|---|---|
| `schema` | Dotted lowercase name | What this document is |
| `schema_version` | Integer, at least 1 | Which revision of it |

A payload may not use either name; the collision is refused when the record is
built rather than discovered when it will not parse.

Version numbering starts at 1. Zero would read as "not yet versioned", which is
the state a version exists to rule out.

The shape is not new. `tools/quality/evidence/manifest.py` chose it two phases
earlier and has been readable since; this phase makes it the rule for everything
GLOBIN persists rather than the habit of one harness. The quality tooling cannot
import `globin`, so the two spellings are a genuine duplication — and a contract
test compares them, which is the difference
[`SOURCE_OF_TRUTH.md`](engineering/SOURCE_OF_TRUTH.md) draws between a tripwire
and drift.

---

## Schema evolution

A reader is at one version and a record may be at another. Three cases, and only
one of them is interesting.

**The record is current.** Nothing happens.

**The record is older.** It is migrated forward one version at a time. A
migration may not skip a version: a step from 1 straight to 4 leaves 2 and 3
claimed as readable and never exercised, so the first record that arrives at
version 2 finds the path it needed has rotted.

**The record is newer.** It is **refused**. Code that knew less than the writer
cannot understand the record by ignoring the parts it does not recognise. This
generalises [ADR-0040](adr/0040-evidence-records-every-gate-and-its-schema-version-is-a-contract.md)'s
"version 1 is refused rather than read" to everything GLOBIN stores.

### Classifying a change

Two independent questions, because a change can be safe in one direction and not
the other — which matters to anyone deploying readers and writers separately.

*Backward*: can the new code read old records? Only if every field it requires
already existed.

*Forward*: can the old code read new records? Only if every field it requires
still exists. Unknown fields are ignored by every reader, which is what makes
this possible at all.

| Answer | Meaning | What to do |
|---|---|---|
| `full` | Readable both ways | Deploy in any order |
| `backward` | New code reads old records only | Deploy readers first |
| `forward` | Old code reads new records only | Migrate the data first |
| `none` | Readable neither way | Bump the version and write a migration |

Adding an optional field is `full`. Adding a required one is `forward`. Removing
a required one is `backward`. Renaming a field is `none` — it is a removal and an
addition at once, which is why a rename needs a migration and not a deploy note.

**Narrowing a type in place is forbidden outright**, rather than classified.
Invariant 22 already forbids silent data loss, and the classification above works
on field names and requiredness — it cannot see that a field's type changed, so
it must not be relied on to catch it. Widen the schema, migrate, then remove.

---

## Wire forms

| Value | Stored as | Why |
|---|---|---|
| `Decimal` | Text, exponent intact | A float read back is not always the number written |
| `Instant` | Integer epoch milliseconds | ADR-0035 settled the unit; sub-millisecond input is refused |
| `Duration` | Integer nanoseconds | The unit it already holds, so nothing is lost |
| `Currency` | Its code | — |
| `Symbol` | `BASE/QUOTE` | `BTCUSDT` does not say where the base ends |
| `Quantity` | `{amount, currency}` | A denomination recovered by splitting text is one bad delimiter from unit confusion |
| `Price` | `{amount, symbol}` | As above |
| `Side`, `Rounding` | The member value | The stated contract, not the Python identifier |

**A float never appears**, in either direction.
[`VALUE_TYPES_POLICY.md`](VALUE_TYPES_POLICY.md) refuses to build a magnitude
from one, and accepting one at the storage boundary would reintroduce exactly
what that refuses at the construction boundary.

**Trailing zeros are preserved.** `0.10` and `0.1` are the same number and
different statements: `Increment` documents its trailing zeros as the venue's own
declaration of its precision, so normalising would discard information the venue
supplied.

### A monotonic reading is not stored

[`TIME_POLICY.md`](TIME_POLICY.md) records that a monotonic reading's reference
point is undefined and that readings from different processes are not comparable.
A stored one is therefore a number the reader cannot compare with anything it
has. There is no encoder for it, and a contract test asserts there continues not
to be — an absence does not show up in a diff, so the first person to want one
would add it reasonably and nothing would object.

Store the `Instant` the work happened at, or the `Duration` that elapsed. Both
mean something to a later reader.

---

## The representation

JSON, through `globin.ports.serialization.Codec`. Readable without tooling, in
the standard library so [ADR-0003](adr/0003-zero-budget-open-source-dependency-policy.md)
has nothing to weigh, and already what the quality evidence is written in.

Rendering is deterministic: keys sorted, no cosmetic whitespace, ASCII output, no
trailing newline. Sorting is what lets a digest over stored bytes mean anything
([`ENGINEERING_CONTRACT.md`](engineering/ENGINEERING_CONTRACT.md) invariant 3).
The terminator belongs to whoever writes the file.

Three of `json`'s defaults break round-trip identity and are each closed rather
than documented as a caveat:

- **Non-string keys are coerced.** `json.dumps({1: "a"})` returns `{"1": "a"}`
  without complaint, so the document read back is not the one written.
- **`NaN` and `Infinity` are accepted.** RFC 8259 defines neither, so a file
  containing one is readable by Python and by very little else.
- **Floats are native**, so nothing in `json` itself would stop one.

---

## Storage widths

An identifier is stored as text of at most **64** characters. The number is
derived from the identifier registry rather than written down, so registering a
kind with a longer bound moves it automatically —
[`IDENTIFIER_POLICY.md`](IDENTIFIER_POLICY.md) deferred this width to Phase 012
by name, and a literal here would have to be remembered by somebody.

Characters, not bytes. What a storage engine multiplies that by is its encoding's
business.

A schema name is at most 96 characters, drawn from lowercase letters, digits and
the dot that separates namespace from thing. It may not begin or end with a dot,
because that names an empty segment.

---

## What this policy does not decide

**Where a record is stored.** There is no `save`, no `load`, no path and no
handle anywhere in this phase. Turning text into a file or a row belongs to the
phases that own somewhere to put one: Phase 159 for backtest results, Phase 190
for models, Phase 266 for orchestration state.

**Which records exist.** The authoritative schemas for datasets are Phase 098's.
This phase fixes the rules every one of them obeys, so that Phase 098 chooses
fields rather than re-deciding how a decimal is written.

**A venue's spelling.** `BTC/USDT` is GLOBIN's form. Translating to whatever
Binance publishes is Phase 034's, at the boundary that talks to it.

**Compression, encryption or signing.** None is in scope for any phase yet.

---

## Related documents

- [`docs/VALUE_TYPES_POLICY.md`](VALUE_TYPES_POLICY.md) — what the values mean
- [`docs/PRECISION_POLICY.md`](PRECISION_POLICY.md) — why magnitudes are exact
- [`docs/TIME_POLICY.md`](TIME_POLICY.md) — instants, durations and readings
- [`docs/IDENTIFIER_POLICY.md`](IDENTIFIER_POLICY.md) — what may be a name
- [ADR-0041](adr/0041-serialization-is-exact-or-refused-and-a-version-is-refused-when-unknown.md) — the decision this document describes
