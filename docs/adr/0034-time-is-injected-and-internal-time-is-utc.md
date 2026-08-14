# ADR-0034 — Time is an injected clock behind two ports, and internal time is UTC

## Status

Accepted — Phase 009.

**Date:** 2026-08-14

## Context

`ENGINEERING_CONTRACT.md` invariant 25 has said since Phase 002 that
timezone-naive datetimes must not cross a domain boundary, that internal time is
UTC, and that wall-clock time is injected rather than read. Its last sentence
named this phase as the one that would deliver the discipline.

[ADR-0026](0026-correlation-is-bound-explicitly-not-ambiently.md) had to decide
what to do about a timestamp three phases early. It refused to build a clock
port — "the phase that owns time will decide monotonic versus wall clock,
millisecond conventions and the shape of the port" — and instead had
`StreamLogSink.emit` call `datetime.now(UTC)` as it serialised, so that the
domain stayed deterministic and Phase 009 inherited "one call to replace, in one
adapter". Its Risks section called that "a bet on Phase 009 arriving". The bet
paid: the change touched five construction sites, and
`tests/property/test_observability_properties.py` needed no edit at all.

**Nothing here supersedes that record.** It decided that Phase 006 would not
build a clock, which was correct then and is unchanged now; this record decides
what Phase 009 built instead. Accepted ADRs are immutable, so the six forward
references inside ADR-0026 stay exactly as written — they were accurate on their
date, and the place a reader learns the bet was settled is here.

Auditing the tree for this phase turned up something nobody had noticed. The
rule "wall-clock time is never read ambiently" was **not enforced anywhere**, and
two checks that look as though they would enforce it do not:

- `docs/architecture/dependency-rules.toml` forbids an inner layer importing an
  I/O-capable module, but neither `time` nor `datetime` was on that list. A
  domain module could `import time` and call `time.monotonic()` with nothing
  failing.
- Ruff's `DTZ` family, selected since Phase 004, refuses naive constructions
  repository-wide. It enforces *awareness*. `datetime.now(UTC)` in the domain
  layer passes it cleanly, because location is not what those rules are about.

So the invariant was written down and trusted, which `MEMORY.md` lists as
precisely the thing this repository does not do.

## Decision

**1. Internal time is an `Instant`** — a frozen slotted wrapper over a
timezone-aware UTC `datetime`. Never a subclass of `datetime`, never a bare
`int`. The subclassing prohibition is
[ADR-0030](0030-domain-values-are-denominated-wrappers-over-decimal.md)'s
argument restated: a subclass would be interchangeable with the thing it wraps
exactly where the distinction matters.

**2. A naive datetime is refused at construction**, using the documented
aware/naive test. An aware datetime at another offset is **converted** by the
`instant()` factory and refused by the constructor. Conversion is arithmetic on
an unambiguous moment; accepting a naive one would be inventing information.
This is the same split `Quantity` and `quantity()` already use.

**3. Anything a `tzinfo` raises becomes a `ValidationError`.**
`datetime.utcoffset()` is a call into caller-supplied code and raises
`TypeError` or `ValueError` for a misbehaving implementation; `astimezone`
raises `OverflowError` near the ends of the calendar. None is a
`globin.errors` type, and [ADR-0022](0022-error-taxonomy-rooted-in-one-type.md)
requires that a fault leaving a boundary is one.

**4. Wall time and monotonic time are two ports, not one with two methods.**
They carry incompatible guarantees, and the decisive reason is Phase 040: a
clock reporting the venue's server time can honestly implement `Clock` and has
no monotonic reading to offer. One combined port would oblige it to invent one.

**5. `Instant` orders but does not subtract.** The difference between two
wall-clock readings is not an elapsed time — the host clock reports
`adjustable=True`, and an operator or an NTP correction can step it. An operator
that silently returned a duration would make the wrong measurement easy to write
and impossible to notice.

**6. The adapter uses `monotonic_ns`, not `perf_counter_ns`,** on the guarantee
rather than the resolution. On the declared host the two are the same source, so
the choice costs nothing measurable and is therefore a pure contract choice.

**7. `time` joins `io.capable_modules`; `datetime` deliberately does not.**
`time` is entirely a clock-and-sleep module, so banning the import is exact.
Banning `datetime` would make invariant 25 unimplementable, since the invariant
presupposes aware datetimes crossing the boundary. The narrower rule — no clock
is *read* outside the adapters layer — is enforced by an AST check in
`tests/architecture/test_clock_discipline.py`.

**8. The test doubles live in `tests/support.py`, never in `globin.adapters`.** A
fixed clock shipped in the package would become the path of least resistance for
production code wanting deterministic time.

## Consequences

`StreamLogSink` gains a **required** `clock` field. It cannot be optional:
`clock: Clock = SystemClock()` and `field(default_factory=SystemClock)` are both
calls in a class body, which `test_layer_modules_execute_no_work_when_imported`
refuses. The architecture rule and the design rule happen to agree, and every
component that timestamps must now be given a clock — visible friction, and the
intended kind.

One test got materially stronger rather than merely being updated.
`test_the_written_line_carries_a_timezone_aware_timestamp` could previously only
assert that the timestamp ended in `+00:00`, because the clock was ambient. It
now asserts the exact value, and a second test asserts the clock is read once
per record rather than cached — a defect that would look like a working
timestamp until someone tried to order two records by it.

`MonotonicClock` ships with no consumer. `ROADMAP.md` names "monotonic clocks"
in this phase, and the decision worth fixing now is which guarantee an elapsed
measurement rests on; the first call site arrives with the code that needs one.

The AST check is a proxy, not a proof — the same word
`dependency-rules.toml` already uses about I/O imports.

## Alternatives Considered

**Store epoch milliseconds as the representation.** Simpler, and it matches the
wire. Rejected because it truncates at the door: the system clock produces
microseconds, and invariant 22 forbids discarding them silently. The venue
convention is a property of the wire, not of GLOBIN.

**One `Clock` port with both `now()` and a monotonic method.** Fewer types,
fewer injections. Rejected on Phase 040: a server-time clock would have to
implement a monotonic method it cannot honestly provide.

**A module-level `SYSTEM_CLOCK` singleton.** Convenient at every call site.
Rejected twice over — it is hidden global state under invariant 5, and
constructing it is a call at import, which the architecture suite refuses.

**Freeze time in tests by patching `datetime.now`.** The conventional approach,
and the one most contributors expect. Rejected on the same reasoning ADR-0026
already gave for the seam: a patch makes every test depend on a global, and
`TESTING_STRATEGY.md` prefers a seam to a patch.

**Ban `datetime` from the inner layers outright.** Symmetrical with `time`, and
it would need no AST rule. Rejected because invariant 25 requires aware datetimes
to cross the domain boundary, so the domain must be able to name the type.

**Put `Instant` in `domain/values.py`.** It is a value type and that module
holds the value types. Rejected on three counts: `test_values_contract.py`
sweeps that module's uppercase constants against the *value types* policy, so
six time constants would have to be documented beside `MAX_ADJUSTED_EXPONENT`;
`VALUE_TYPES_POLICY.md` currently defers timestamps to this phase and would then
contradict itself in one file; and `MEMORY.md` describes those five types as
denominated by *asset*, which an `Instant` is not.

**Name the module `time.py`** to match the phase title. Rejected for one
concrete reason rather than on taste: this phase adds `"time"` to
`io.capable_modules`, and a reader seeing that entry beside a file called
`domain/time.py` has to work out that the two are unrelated. Ruff's A005 does
not fire either way, since the module is not top-level.

## Risks and Trade-offs

**The characteristic failure is an alias.** `from datetime import datetime as
dt` followed by `dt.now(UTC)` defeats the AST check, because it matches call
spellings. The observable signal is a domain module whose behaviour depends on
when it runs while the architecture suite stays green. The mitigation is that
the honest spellings are the convenient ones, so the check catches erosion
rather than evasion.

**A required field is friction, and friction gets routed around.** Nothing stops
a contributor writing `SystemClock()` inline inside an adapter rather than
accepting one. That is legal — adapters may read clocks — but it puts ambient
time back one layer out. The signal is a second module appearing in
`test_only_the_clock_adapter_reads_a_clock`, which fails when it does.

**Windows clock resolution is a flake source.** On the declared host both clocks
report `1e-07`, but that is a property of this machine and this CPython build.
Where the wall clock falls back to `GetSystemTimeAsFileTime()` the granularity is
about 15.6 ms and two consecutive reads return the same value. No test may
assert that two real readings differ; `tests/unit/test_clock.py` says so in its
docstring and asserts `>=` throughout.

## References

- [`../TIME_POLICY.md`](../TIME_POLICY.md) — the register this record decides the shape of
- [`../engineering/ENGINEERING_CONTRACT.md`](../engineering/ENGINEERING_CONTRACT.md) — invariants 3, 5, 22, 25
- [ADR-0026](0026-correlation-is-bound-explicitly-not-ambiently.md) — the deferred timestamp and the seam it left
- [ADR-0030](0030-domain-values-are-denominated-wrappers-over-decimal.md) and [ADR-0031](0031-value-types-compare-but-do-not-compute.md) — the value-type shape this follows
- [ADR-0022](0022-error-taxonomy-rooted-in-one-type.md) — why a foreign exception is translated
- [ADR-0035](0035-milliseconds-are-a-floored-projection.md) — the millisecond half of this phase
- [`../architecture/dependency-rules.toml`](../architecture/dependency-rules.toml)
- [`../research/phase_009_sources.md`](../research/phase_009_sources.md)
- [`../../ROADMAP.md`](../../ROADMAP.md) — Phase 009, and Phase 040 which owns synchronisation

## Supersedes

None.

## Superseded By

None.
