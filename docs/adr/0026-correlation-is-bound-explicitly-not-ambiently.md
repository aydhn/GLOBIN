# ADR-0026 — Correlation is bound explicitly, and the timestamp belongs to the adapter

## Status

Accepted — Phase 006.

**Date:** 2026-08-14

## Context

[ADR-0025](0025-structured-logging-is-a-redacted-domain-event.md) settles what a
log record *is*. Two questions it leaves open are about where two particular
values come from, and both have a conventional answer that this repository's
existing rules reject.

**Correlation.** The roadmap asks for logging that is *correlation-aware*: the
records produced by one piece of work must be findable as a group. The usual
mechanism is a `contextvars.ContextVar` set at an entry point and read by
whatever logs, so that no code in between has to carry anything. It is genuinely
convenient, and it is ambient global state —
[`ENGINEERING_CONTRACT.md`](../engineering/ENGINEERING_CONTRACT.md) invariant 5
forbids hidden global state, and invariant 3 requires determinism. It also
interacts badly with the process-state isolation
[ADR-0024](0024-tests-are-offline-and-isolated-by-construction.md) established
one phase ago: a context variable left set by one test changes what a later test
records, which is the class of failure that fixture exists to make impossible.

**Time.** Every record needs a timestamp, and reading a clock is
nondeterministic. Phase 009 — *Time, Clock and Timezone Discipline* — owns
UTC-only internal time, millisecond conventions and an injectable clock
abstraction. Phase 006 needs a timestamp three phases before the phase that
decides how time works. Building a clock port now would be implementing Phase
009 early, which [`ROADMAP.md`](../../ROADMAP.md) rule 5 calls a defect;
ignoring the problem would mean a domain object that reads the system clock,
which makes every event untestable without freezing something.

## Decision

**1. A `Logger` is an immutable value carrying its own correlation id and
context.** `globin.application.observability.Logger` is a frozen dataclass
pairing a sink with a correlation id and bound fields.

**2. `bind` returns a new logger.** It never mutates. Passing a logger into a
function therefore cannot change what the caller subsequently logs, and a
logger's output is a function of what was bound to it rather than of what ran
before it.

**3. There is no `contextvars` and no ambient correlation.** The cost is an
argument at each boundary. What it buys is that the context on a record is
visible in the code that produced it.

**4. Correlation ids are supplied, not discovered.** `build_logger` generates one
when the caller does not pass one, using `uuid4` in the adapter layer. Generation
reads a source of randomness, so it lives beside the clock rather than in the
domain, and a test passes its own id.

**5. `LogEvent` carries no timestamp. The adapter stamps it.**
`StreamLogSink.emit` calls `datetime.now(UTC)` as it serialises. The domain stays
deterministic, Phase 009 is not pre-empted, and the seam it will need is already
in the right place: an injectable clock replaces one call in one adapter.

**6. Timestamps are timezone-aware and UTC.** This is the logging half of what
Phase 009 will state generally, committed now because a naive timestamp written
today is a data problem later. Ruff's `DTZ` rules already enforce it repository-wide.

## Consequences

- A component that logs must be given a logger. That is visible in constructors
  and is the intended pressure: it makes the dependency explicit rather than
  ambient.
- Two loggers bound with the same fields compare equal, because context is stored
  as sorted pairs. Tests can assert on a logger rather than on what it emitted.
- Phase 009 has one call to replace, in one adapter, rather than a convention to
  retrofit across the codebase.
- Correlation does not cross a process or a thread boundary by itself. Nothing in
  GLOBIN is concurrent yet; when something is, the id is passed like any other
  value, which is the same mechanism rather than a new one.
- `tests/integration/test_logging_end_to_end.py` can assert that three records
  share a correlation id without controlling any global state.

## Alternatives Considered

**A `contextvars.ContextVar` for the correlation id.** The conventional design,
and the one most contributors will expect. Rejected on invariant 5, and on the
test-isolation interaction: `ADR-0024` added an autouse fixture that fails a test
for leaking an environment variable, and a context variable is the same failure
wearing different clothes. It would also have made the correlation id on a record
depend on the call stack rather than on the logger, which is precisely the
property that makes ambient context hard to reason about during an incident.

**A mutable `Logger` with a `set_correlation` method.** Cheaper at call sites,
since one logger can be reconfigured in place. Rejected because a logger stored
on a long-lived object would then change under its holder, and two components
sharing a logger would silently share its context.

**Generate the correlation id inside `LogEvent` when one is not supplied.**
Convenient, and it would make the field impossible to forget. Rejected because it
puts a randomness source in the domain layer and makes every event's identity
nondeterministic — two events built from identical inputs would not compare
equal, which defeats the canonical ordering ADR-0025 decided.

**Define a minimal clock port now and inject it.** Tempting, and it is what
Phase 009 will do. Rejected as scope leakage: the phase that owns time will
decide monotonic versus wall clock, millisecond conventions and the shape of the
abstraction, and a port invented here would either be replaced or would
constrain that decision without having done the work behind it.

**Let the domain read the clock and freeze it in tests.** Rejected because
freezing time in tests requires either a dependency or patching a standard
library call, and `TESTING_STRATEGY.md` prefers a seam to a patch.

## Risks and Trade-offs

The characteristic failure is **a correlation id that is not passed on**. Nothing
enforces that a function handed a logger uses it rather than building its own, so
a records-of-one-unit-of-work group can silently split. Ambient context would
have made this impossible at the cost of making everything else harder to reason
about. The mitigation available today is that the id is visible in a signature;
the observable signal is a trace that stops mid-operation, and if that becomes
common the answer is a lint rule or a review convention rather than reversing
this record.

**Explicit binding is friction, and friction can be routed around.** A
contributor who finds passing a logger tedious can construct one wherever it is
needed, defeating the point without breaking a test. The cost is invisible until
someone tries to follow a unit of work through the output.

**The timestamp decision is a bet on Phase 009 arriving.** Until it does, one
adapter calls the system clock directly, and any test wanting to assert on a
specific timestamp must go through `as_record`, which takes the timestamp as an
argument for exactly that reason. If Phase 009 slipped a long way, that seam is
the only thing keeping time testable.

## References

- [`../../ROADMAP.md`](../../ROADMAP.md) — Phase 006, and Phase 009 which owns time.
- [ADR-0025](0025-structured-logging-is-a-redacted-domain-event.md) — the record
  shape and the port this record supplies two values for.
- [ADR-0024](0024-tests-are-offline-and-isolated-by-construction.md) — the
  process-state isolation that ambient context would have undermined.
- [`../LOGGING_POLICY.md`](../LOGGING_POLICY.md) — how correlation is used in practice.
- [`../engineering/ENGINEERING_CONTRACT.md`](../engineering/ENGINEERING_CONTRACT.md) —
  invariants 3, 5 and 25.
- [`../research/phase_006_sources.md`](../research/phase_006_sources.md) — the
  external evidence this phase relied on.

## Supersedes

None.

## Superseded By

None.
