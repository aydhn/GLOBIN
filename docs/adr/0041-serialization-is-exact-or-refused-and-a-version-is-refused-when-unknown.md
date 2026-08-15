# ADR-0041 — Serialization is exact or refused, and an unknown version is refused rather than read

## Status

Accepted — Phase 012.

**Date:** 2026-08-15

## Context

`ROADMAP.md` assigns Phase 012 to *Serialization and Persistence Contracts*:
schema evolution rules, and forward and backward compatibility guarantees for
persisted structures. Five places in the repository already defer to it by name —
`ENGINEERING_CONTRACT.md` invariant 20 ("Serialization contracts are **Phase
012**"), [ADR-0032](0032-verification-tooling-may-be-added-outside-phase-scope.md),
[ADR-0035](0035-milliseconds-are-a-floored-projection.md), a comment in
`globin.domain.identifiers` about "a database column of the size Phase 012 will
choose", and `tests/contract/test_error_taxonomy_contract.py`.

Two things were already settled and had to be inherited rather than re-decided.
ADR-0035 fixed the wire form of an instant as a whole number of milliseconds.
[ADR-0030](0030-domain-values-are-denominated-wrappers-over-decimal.md) and
[ADR-0037](0037-arithmetic-is-exact-or-refused-under-an-explicit-context.md)
fixed magnitudes as exact decimals that a float may never construct.

One thing was open and is the reason this record exists. `Instant.epoch_millis`
**floors**, and a `datetime` carries microseconds. Encoding an instant by calling
that projection would therefore mean a value read back is not the value written,
for every instant that did not happen to land on a millisecond. That is silent
narrowing, which `ENGINEERING_CONTRACT.md` invariant 22 forbids — and it would be
invisible, because each individual step is correct.

`tools/quality/evidence/manifest.py` had meanwhile solved the versioning half by
hand, two phases earlier: an envelope carrying `schema` and `schema_version`, in
which version 1 is refused rather than read. It works, and nothing said whether
it was one harness's habit or the project's rule.

## Decision

**1. Serialization is exact, or it is refused.** Every encoder either produces a
value that reads back identical, or raises. None narrows. This is deliberately
the same sentence ADR-0037 makes about arithmetic, arrived at from a different
premise: a stored value is compared against itself later, so a lost digit breaks
`decode(encode(x)) == x` rather than merely costing precision.

**2. `encode_instant` refuses sub-millisecond precision rather than flooring
it.** ADR-0035 is unchanged and remains right about *requests*, where a timestamp
that has drifted into the future is the one an exchange rejects. A record is not
a request. A caller who wants the floor writes `instant.epoch_millis`, which is
one line and says which of the two they meant.

**3. An unknown version is refused, never guessed.** A record newer than its
reader is refused outright. The plausible alternative — ignore the unrecognised
keys and read the rest — silently discards the field the newer writer added
because it mattered. This generalises ADR-0040's rule for the evidence manifest
to everything GLOBIN persists.

**4. A migration advances exactly one version.** A step from 1 straight to 4
would leave 2 and 3 claimed as readable and never exercised, so the first record
arriving at version 2 would find the path it needed had rotted. Composing single
steps costs a few calls.

**5. Compatibility is two independent answers, not one boolean.** *Backward* is
whether new code can read old records; *forward* is whether old code can read new
ones. A change can be safe in one direction and not the other, which is exactly
what somebody deploying readers and writers separately has to know. Narrowing a
type in place is forbidden outright rather than classified, because the
classification works on names and requiredness and cannot see a type change.

**6. A monotonic reading has no wire form.** `globin.domain.clock` documents its
reference point as undefined and readings from different processes as
incomparable, so a stored one is a number the reader cannot compare with
anything. A contract test asserts the absence persists, because an absence does
not appear in a diff.

**7. The representation is JSON behind a port, and three of the standard
library's defaults are closed.** Non-string keys are silently coerced
(`json.dumps({1: "a"})` is `{"1": "a"}`), `NaN` and `Infinity` are accepted
though RFC 8259 defines neither, and floats are native so nothing would stop one.
Each is refused in both directions rather than documented as a caveat.

**8. The identifier storage width is derived, not written down.** It is the
largest `max_length` in the identifier registry — 64 characters today.
Registering a longer kind moves it automatically, where a literal would have to
be remembered.

## Consequences

`globin.domain.serialization` is the one place that decides how a GLOBIN value is
written, and `globin.domain.values` no longer has to say "no wire format is
decided here". Phase 098 chooses fields for its canonical schemas rather than
re-deciding how a decimal is spelled.

Callers pay for decision 2. Any code holding an instant from a source finer than
a millisecond must floor it explicitly before storing it. That is the intended
cost: the alternative is that nobody ever notices.

The evidence manifest's envelope is now the project's rule, and a contract test
compares the two spellings. The quality tooling still cannot import `globin`
(`test_evidence_contract.py` asserts it never does), so they remain a genuine
duplication with a tripwire rather than a shared constant.

Nothing stores anything yet. There is no `save`, no `load` and no path anywhere
in this phase, and the port carries none — storage belongs to the phases that own
somewhere to put a record.

## Alternatives Considered

**Floor on the way in, matching `epoch_millis`.** Simpler, and it is what a
reader would expect from the projection already published. It was refused because
it makes every stored instant potentially different from the one written, with
nothing raising — the exact failure invariant 22 names. The refusal is noisy
once, at the call site, where somebody can decide.

**Store an instant as ISO 8601 text.** Preserves microseconds, so decision 2's
refusal would not be needed. Rejected because it puts two spellings of an instant
into the system: ADR-0035 already settled milliseconds for the wire, and a record
that disagreed with the request it describes is a reconciliation nobody asked
for. Text is also more expensive to compare and to index.

**Let a reader ignore unknown fields and read a newer record anyway.** Common,
and superficially friendly. Rejected because the field a newer writer added is
the one worth having, and a reader that skips it produces a plausible answer from
incomplete data — the worst available outcome.

**Model field types, so that narrowing could be classified rather than
forbidden.** More complete. Rejected because it means inventing a type vocabulary
in the foundation band, and the authoritative schemas that would need one belong
to Phase 098. A rule stated in the policy and enforced by review is honest about
what the code checks; a classifier that silently could not see type changes would
not be.

**Put JSON rendering in the domain as plain functions**, as
`tools/quality/evidence/manifest.py` does, with no port. Rejected, narrowly. It
would be the smaller change and the codec performs no I/O. But *which*
representation GLOBIN persists in is an outside-world commitment, and Phases 159
and 190 may want a columnar one; the seam is where a second implementation
arrives without the domain learning about it.

## Risks and Trade-offs

The characteristic failure is that decision 2 is experienced as an obstacle. Some
future caller will hold a microsecond instant, want to store it, and reach for a
truncation somewhere upstream — putting the narrowing back one layer further away
from where it can be seen. The observable signal is a call to `epoch_millis`
whose result is stored without the caller having said why. It should be answered
by asking whether the extra precision mattered, not by softening the encoder.

Decision 7 makes the codec stricter than JSON. A document written by another tool
— with a float in it, quite legitimately — cannot be read by this codec at all.
That is correct for a GLOBIN record and would be wrong for a general-purpose JSON
reader, and the distinction rests on nobody using this to read foreign documents.

Decision 5 gives a classification that is sound but incomplete: it answers about
presence and requiredness only. Somebody may read a `full` verdict as "this
change is safe" when the change also narrowed a type. The policy states the
limitation in the same section as the table, which is the best available
mitigation short of Phase 098's work arriving early.

## References

- [`docs/SERIALIZATION_POLICY.md`](../SERIALIZATION_POLICY.md)
- [`docs/engineering/ENGINEERING_CONTRACT.md`](../engineering/ENGINEERING_CONTRACT.md), invariants 3, 20 and 22
- [ADR-0030](0030-domain-values-are-denominated-wrappers-over-decimal.md)
- [ADR-0035](0035-milliseconds-are-a-floored-projection.md)
- [ADR-0037](0037-arithmetic-is-exact-or-refused-under-an-explicit-context.md)
- [ADR-0040](0040-evidence-records-every-gate-and-its-schema-version-is-a-contract.md)
- RFC 8259, *The JavaScript Object Notation (JSON) Data Interchange Format*

## Supersedes

None.

## Superseded By

None.
