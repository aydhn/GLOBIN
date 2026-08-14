# ADR-0025 — A log record is a domain event that redacts itself, emitted through a port

## Status

Accepted — Phase 006.

**Date:** 2026-08-14

## Context

[`ROADMAP.md`](../../ROADMAP.md) assigns Phase 006 *Structured Logging
Foundation*: structured, correlation-aware logging with a severity policy and
redaction of sensitive fields. Three existing rules constrain how that can be
built, and together they leave less room than the brief suggests.

**Only the outer layers may log.** `docs/architecture/dependency-rules.toml`
lists `logging` among the I/O-capable modules, and `domain`, `ports` and
`application` all declare `may_perform_io = false`. So
`tests/architecture/test_architecture_contract.py` fails the build if an inner
layer imports it. Whatever logging looks like, it cannot look like a module-level
`getLogger` in every file.

**Nothing may run at import.** [ADR-0015](0015-single-composition-root-and-no-import-time-side-effects.md)
and the import-time check in the same test forbid work at import in any layer
package — the check follows class bodies, so even a module-level `frozenset(...)`
is a violation. The conventional `logger = logging.getLogger(__name__)` line is
unavailable on both counts.

**Secrets must not be written, at any severity.**
[`ENGINEERING_CONTRACT.md`](../engineering/ENGINEERING_CONTRACT.md) invariant 24
states this absolutely: no severity level, no debug flag and no local-only
exception permits writing a live credential to an output stream. Invariant 10
asks for observability that does not leak secrets. Neither is satisfied by a
rule contributors are asked to remember.

The obvious design — a thin wrapper over the standard library's `logging`, with
a filter that scrubs records on the way out — satisfies none of the three
cleanly. Filters run in the sink, which means the unredacted record exists first
and the guarantee holds only as long as every sink is correctly configured.

## Decision

**1. A log record is a domain value.**
`globin.domain.observability.LogEvent` holds a severity, a static event name, a
correlation id and sorted fields. It is a frozen dataclass in the innermost
layer, so it is constructible and assertable without a stream, a clock or a
configuration.

**2. Redaction happens in `__post_init__`, not in a sink.** An unredacted
`LogEvent` cannot be constructed. A field whose *name* matches any fragment of
`SENSITIVE_KEY_FRAGMENTS` has its *value* replaced before the object exists,
recursively through nested mappings and sequences. A sink added in a later phase
inherits the guarantee rather than being trusted with it.

**3. Matching is a case-insensitive substring test, biased to over-redaction.**
`binance_api_key` is precisely the field that must not be printed, and an
exact-set rule would miss it. The cost is that `token_count` loses a harmless
integer. Given invariant 24 is absolute, the asymmetry is the right way round.

**4. Call sites name events and attach fields; they never interpolate.** This is
what makes rule 2 sufficient. If a value can only arrive as a field, inspecting
field names catches every value. The moment a secret can be formatted into a
message, no rule about names can help.

**5. Emission goes through a one-method port.**
`globin.ports.observability.LogSink` declares `emit`. Where a record ends up is
an adapter concern; `StreamLogSink` writes JSON Lines to a stream the composition
root supplies.

**6. The standard library's `logging` is not used.** GLOBIN has no runtime
dependencies, so nothing else in the process emits records. Routing through
`logging` would buy interoperability nobody needs at the price of module-level
handler state — the global configuration invariant 5 exists to keep out. When a
dependency first emits standard-library records, a second `LogSink` bridges
them: an addition behind the port, not a rewrite.

**7. Coercion is total and writes propagate.** A value JSON cannot represent is
written as its `repr`, and non-finite floats as text, so a logging call cannot
raise. A failed write is not caught, because a sink that silently discards
records is indistinguishable from a working one until you need the log. The
owner was asked and chose both.

## Consequences

- Four modules appear, one per layer, following the `architecture.py` precedent:
  `domain`, `ports`, `application` and `adapters` each gain `observability.py`,
  and `runtime/composition.py` gains `build_logger`.
- The architecture suite needs no new cases. It reads the real import graph, so
  an inner layer importing `logging` fails automatically — the existing test is
  the proof that this design is the one in place.
- `docs/LOGGING_POLICY.md` owns the severity meanings and the redacted-name
  list, and `tests/contract/test_observability_contract.py` compares that
  document against the code bidirectionally. A fragment listed in one and absent
  from the other fails the build.
- Every later phase inherits a logger it cannot leak a credential through. That
  matters most from Phases 033-048, when there is a credential to leak.
- Redaction copies rather than aliasing, so an event never shares structure with
  the caller's dictionary. Logging a large nested structure costs a copy.

## Alternatives Considered

**Wrap the standard library's `logging` and scrub in a filter.** The
conventional design, and the cheapest to write. Rejected because the unredacted
record exists before the filter runs, so the guarantee is only as strong as the
handler configuration — which is global, mutable, and exactly what invariant 5
excludes. It would also have put `logging` on the import path of any module
wanting to log, which the layer contract refuses.

**Redact in the sink rather than in the event.** Keeps the domain smaller, and
was rejected for the reason that makes rule 2 worth having: it moves the
guarantee to the one place a later contributor is most likely to add a second
implementation of. Two sinks means two chances to forget.

**Accept a formatted message alongside fields.** Familiar, and it would make
adoption easier for anyone used to `logging`. Rejected because it silently
reopens the hole: `logger.info(f"key={api_key}")` is unstoppable by any rule
about field names, and a policy that is enforceable except when someone uses the
convenient parameter is not enforceable.

**Model severity as a `StrEnum` rather than borrowing the standard library's
numbers.** Cleaner in isolation. Rejected because thresholds become string
comparisons and any future bridge needs a mapping table, and a mapping table
between two enumerations is a thing that drifts silently.

## Risks and Trade-offs

The characteristic failure is **a secret arriving under a name nobody listed**.
Substring matching over a fixed list catches `binance_api_key` and misses
`x_auth_material`. Nothing here detects a secret by its shape, and deliberately
so: a value-based heuristic that scans every field for things resembling
credentials is both expensive on a hot path and confidently wrong at the edges.
The mitigation is that Phase 015 owns the security baseline and inherits this
list as the place its field-name half lands — but between now and then the list
is the whole defence, and it is only as good as the names people choose.

A second, quieter risk: **over-redaction is invisible**. A field called
`token_count` returns `[redacted]` and nobody notices until an operator needs the
number during an incident. The name survives redaction precisely so this is
diagnosable, but the failure mode is real and the fix — narrowing a fragment —
weakens the defence it came from.

**Not using `logging` has a date on it.** The reasoning holds while GLOBIN has no
runtime dependencies. Phases 021-022 introduce the first, and if one emits
standard-library records they will go nowhere until the bridging sink exists.
The observable signal is a dependency whose diagnostics are missing from GLOBIN's
own output, and the answer is a second sink rather than a revision here.

## References

- [`../../ROADMAP.md`](../../ROADMAP.md) — Phase 006 and its purpose.
- [`../LOGGING_POLICY.md`](../LOGGING_POLICY.md) — the policy this record decided.
- [ADR-0014](0014-layered-ports-and-adapters-and-inward-dependencies.md) and
  [ADR-0015](0015-single-composition-root-and-no-import-time-side-effects.md) —
  the layer contract and the import-time rule that shaped this design.
- [ADR-0022](0022-error-taxonomy-rooted-in-one-type.md) — the error taxonomy the
  validation in `LogEvent` raises through.
- [ADR-0026](0026-correlation-is-bound-explicitly-not-ambiently.md) — the
  correlation and timestamp half of the same phase.
- [`../engineering/ENGINEERING_CONTRACT.md`](../engineering/ENGINEERING_CONTRACT.md) —
  invariants 5, 10, 23 and 24.
- [`../research/phase_006_sources.md`](../research/phase_006_sources.md) — the
  external evidence this phase relied on.

## Supersedes

None.

## Superseded By

None.
