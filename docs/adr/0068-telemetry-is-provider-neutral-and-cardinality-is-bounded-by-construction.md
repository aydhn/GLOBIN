# ADR-0068 — Telemetry is provider-neutral, and cardinality is bounded by construction rather than policed at runtime

## Status

Accepted — Phase 026.

**Date:** 2026-08-17

## Context

Phase 026 gives GLOBIN a way to measure itself. The obvious implementation is to
pick a provider — OpenTelemetry or Prometheus — and call it from the code being
measured. That is how most systems do it, and it is what this record refuses.

Two failures decide the design, and neither announces itself. The first is
**cardinality**: a metric label carrying an unbounded value — an order id, a
symbol, a request path — multiplies a metric family into as many series as there
are values, and the failure appears as memory exhaustion or a monitoring bill
rather than as an error anybody can trace back to the call site. The second is a
**provider type reaching the core**: once a domain object holds an OpenTelemetry
instrument, replacing the provider is a rewrite rather than an adapter swap, and
the provider's own vocabulary starts deciding what GLOBIN is allowed to measure.

A third consideration is specific to this repository. `JsonCodec` refuses a `float`
at any depth of a persisted document, so a telemetry value cannot be a float
without either weakening that rule or refusing to persist telemetry at all.

## Decision

**1. GLOBIN declares its own names, in its own namespace, and maps to a provider at
the adapter boundary.** Every metric name begins `globin.`; nothing under
`domain`, `ports` or `application` names either library; and
`tests/architecture/test_library_discipline.py` enforces one import site per
library on the real import graph.

**2. A provider name is DECLARED beside the canonical one, never derived from it.**
This is a correctness argument rather than a stylistic one:
`globin.export.batches_offered` and `globin.export.batches.offered` both sanitise
to `globin_export_batches_offered`. A derived mapping merges two distinct series
into one, and the merge is invisible in the code, invisible in the diff, and shows
up as a wrong number on a dashboard months later. A declared table makes that
collision a failing test.

**3. Every attribute key must declare a bounded set of permitted values, and a
descriptor whose product exceeds its own budget cannot be constructed.** This is
the decision that does the most work. Because the domains are bounded, the maximum
series a family can produce is `declared_series(descriptor)` — an arithmetic fact
available when the descriptor is built rather than a number observed in production.
The runtime budget check still exists, and it is **provably unreachable for a
correct registry**: a property test asserts it never fires for anything `metrics()`
returns, and a unit test reaches it only by pre-filling a family by hand.

**4. Screening returns closed reason codes, never sentences, and never the supplied
value.** `member_problems` quotes the offending member because GLOBIN chose that
filename. Here the offending token is arbitrary caller data that could be a
credential, so nothing supplied ever reaches a return value, a log record or a
snapshot.

**5. A credential-shaped attribute is REFUSED where a log field is SUBSTITUTED, and
that contradiction with [ADR-0025](0025-structured-logging-is-a-redacted-domain-event.md)
is deliberate.** A log field is a leaf: substituting it loses one datum. An
attribute is a *dimension*: substituting it merges two series under a name that
means nothing — a real series with a fake identity, which is worse than no series.

**6. Two denylists, disjoint, and the disjointness is asserted.** `is_sensitive` is
imported from `domain/observability.py` rather than restated, and answers *would
this value be a secret*. A second tuple answers a question it cannot: *would this
value be unbounded*. An order id is not a secret and is fatal as a label; an API key
is not high-cardinality and is fatal for another reason. A contract test proves the
two share no fragment and that neither subsumes the other, so "reuse rather than
duplicate" is honest rather than approximate.

**7. Every value is an integer, and the scale is declared per unit.** A duration is
nanoseconds, a ratio is parts per million, bytes and counts are themselves. This
costs nothing on the recording path — `MonotonicReading.since` already returns
integer nanoseconds — and the one float conversion a provider needs happens at the
edge that needs it. The ceiling is `2**53 - 1`, which is **not** Python's limit:
every JSON reader that is not Python holds numbers as doubles and silently drops
low bits past that point, which is the same corruption the float ban prevents
arriving through the integer door.

**8. Export is off by default, and "off" is an object graph rather than a flag.**
With `telemetry.export_enabled` false, no exporter, queue, pump or thread is
constructed, so "GLOBIN opens no socket" is structural. The Prometheus listener is
separately off, binds `127.0.0.1` as a **literal**, and exposes no address setting —
because `prometheus_client.start_http_server` defaults to every interface, and that
is the class of mitigation this repository refuses to leave to memory.

**9. Determinism is claimed narrowly, and `shape()` is the claim.** Two snapshots
taken at different moments differ, because a counter grows and a duration moves.
What is guaranteed for the same logical work — and what a digest may be taken over —
is the family list, its order, the units, the boundaries and the series keys. This
is the split `tools/quality/benchmark/manifest.py` already makes for the one
manifest that is not byte-stable.

**10. Neither library enters `stack-contract.toml`, and the gap that leaves is
recorded rather than hidden.** That contract's libraries feed
`test_stack_discipline.py`'s forbidden-import set, so listing an *adopted* library
would forbid the adapter that exists to import it. The contract cannot currently
express "adopted **and** imported"; `psutil` is absent from it for the same reason.
**The fix is an `adoption` field on the stack schema**, which would let the tripwire
narrow to `verified` entries and would bring the four-registers-of-a-version check
to bear on libraries that are absent in CI and present in production. It is
deliberately not done here, because it is tooling work in a phase that is already
two phases wide.

## Consequences

- Four families are declared and they describe telemetry itself. A descriptor named
  after a capability GLOBIN does not have would be a claim somebody is working on
  it, which is `REPOSITORY_LAYOUT.md`'s rule about directories applied to a register.
- Optional attributes are **impossible**: every declared key must be supplied, or
  one family would have two series shapes and aggregation would break silently. The
  sanctioned answers are a bounded domain with an explicit `"none"` member, or two
  families.
- A telemetry call cannot raise. Every refusal is a drop and a count, and the first
  drop per `(metric, reason)` is logged while the rest are counted — because a
  record per drop turns a cardinality explosion into a log explosion.
- `psutil`'s pattern is now used three times, and the absence of a shared mechanism
  for it is visible.

## Alternatives Considered

**Call a provider directly from the code being measured.** Simplest, and what most
systems do. Rejected on decision 1's reasoning: it makes replacement a rewrite and
lets a provider's vocabulary decide what GLOBIN measures.

**Derive the Prometheus name from the canonical one.** Less to maintain. Rejected on
decision 2's reasoning: the collision it permits is silent and produces a wrong
number rather than an error.

**Police cardinality at runtime only.** The usual approach, and it works — until the
day the limit is reached in production rather than in a test. Refusing at
construction converts the same guarantee from a hope into arithmetic, at the cost of
forbidding unbounded dimensions outright.

**Store durations as floating-point seconds and exempt telemetry from the float
ban.** Rejected: the ban exists because a float does not round-trip exactly, and an
exemption for the subsystem whose whole output is numbers is the worst place to
grant one.

**Bind the Prometheus listener on a configurable address.** Rejected. There is no
operational reason GLOBIN needs one, and a setting would be one typo away from
publishing this process's internals.

## Risks and Trade-offs

**The characteristic failure mode is that bounded dimensions turn out to be too
strict.** A future subsystem will want to label by something genuinely unbounded —
a symbol, an endpoint — and the honest answers are a bounded *classification* of it
(`latency_class` rather than `latency_ms`) or a separate family. **The observable
signal** is a phase proposing to add an `unbounded=True` escape to
`AttributeDomain`. That request should be read as a request to remove this ADR, and
answered accordingly.

**A second risk is that the declared mapping rots.** Contract tests compare it
against the registry in both directions today, but nothing checks it against a real
provider's grammar beyond the name shape. A provider that tightens its rules would
not be noticed until an export failed.

**A third is that the two-list arrangement drifts anyway.** The disjointness test
catches an overlap, not a *gap*: a fragment that belongs on neither list is invisible
to both, and the shape rules (`_id`, `_at`) are what stand between that and a series
explosion.

## References

- [`../engineering/RUNTIME_TELEMETRY.md`](../engineering/RUNTIME_TELEMETRY.md) —
  the subsystem's own document.
- [`../TELEMETRY_POLICY.md`](../TELEMETRY_POLICY.md) — the metric register and the
  attribute rules, compared against the code in both directions.
- [ADR-0025](0025-structured-logging-is-a-redacted-domain-event.md) — the substitution
  rule decision 5 deliberately departs from.
- [ADR-0041](0041-serialization-is-exact-or-refused-and-a-version-is-refused-when-unknown.md) — the float ban decision 7
  works within.
- [ADR-0045](0045-a-platform-capability-is-a-recorded-state-never-a-pass.md) — the
  absence-is-a-state rule both provider bridges apply.
- [`../research/phase_026_sources.md`](../research/phase_026_sources.md) — the
  OpenTelemetry and Prometheus evidence.

## Supersedes

None.

## Superseded By

None.
