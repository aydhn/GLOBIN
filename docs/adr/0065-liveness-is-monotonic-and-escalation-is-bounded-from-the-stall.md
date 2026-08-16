# ADR-0065 — Liveness is a monotonic sequence, and escalation is bounded from the stall

## Status

Accepted — Phase 025.

**Date:** 2026-08-17

## Context

A watchdog has four decisions to get right, and each has an obvious answer that is
wrong.

**What a heartbeat is.** The obvious answer is a timestamp the component rewrites.
But a component looping inside a wedged call rewrites a timestamp indefinitely, so
that measures *reached this line*, not *made progress*.

**What clock measures it.** The obvious answer is the wall clock, because that is
what a threshold in milliseconds looks like. But wall-clock time moves when an
operator corrects it and when a host resumes from sleep, so a threshold compared
against it fires spuriously and stays quiet across exactly the suspend an operator
would want reported.

**When the process dies.** The obvious answer is a grace period starting when the
watchdog asks the process to stop. But then a slow evidence capture postpones the
deadline, and the guarantee becomes "some time after we got round to asking".

**What happens when a component comes back.** The obvious answer is to cancel the
incident. But by then the process has published a record saying it stalled.

Underneath all four is the structural question: where does the state machine live,
given that `threading` is I/O-capable in
[`../architecture/dependency-rules.toml`](../architecture/dependency-rules.toml) and
therefore reachable only from `adapters` and `runtime`?

## Decision

**1. A heartbeat is a sequence, and registration seeds one.** `beat()` increments a
counter; the timestamp moves with it. *Alive* and *progressing* are therefore
different observations, and an incident can say "component `feed` was at sequence 41
when it went quiet and is still at 41". Registration stores a beat at sequence zero,
so "registered and never heard from" is the same subtraction as everything else and
there is no `None` timestamp anywhere.

**2. Beating an unregistered name raises `ValidationError`.** A silent no-op means a
mistyped component is watched by nothing and nothing says so — the failure the
subsystem exists to prevent, reintroduced by its own front door. It can only be a
wiring bug and it fires on the first beat.

**3. Every elapsed quantity is a `Duration` from a `MonotonicReading`.** The single
wall-clock read in the subsystem is an incident's `detected_at`, so a human can find
the moment in a log; nothing compares it against anything.

**4. The escalation deadline is measured from the stall.** `stall_millis +
escalate_millis` after the stall was confirmed, not after the request was made. This
makes it a flat, assertable property: a required component silent for that long ends
the run, whatever the watchdog was doing in between.

**5. Recovery has exactly one inbound edge, and it is structural.** Only `suspect →
healthy`. `transitions()` contains no pair from any settled state back to health, so
the no-rollback rule is an absence in a table rather than a guard somebody can
forget. A late beat is recorded as `watchdog.late.progress` and changes nothing.

**6. Exactly one incident per episode is a property of the graph.** One edge enters
`stalled`, from `suspect`, and `suspect` is unreachable from any settled state. The
machine is thread-confined to the watchdog's own thread, so there is no race and no
lock around it. **The two genuinely shared things live in the adapter**: the
heartbeat table behind one lock — held for a `sequence + 1` and nothing else, never
across disk, a log call or a callback — and the stop latch, which must remain a
plain boolean because `Event.set()` takes a lock and the same latch is written from
a signal handler.

**7. `suspect` is derived, not configured.** It means "silent longer than one poll
interval". A fourth duration would have had to justify itself and could not.

**8. The layer split follows from 6.** `domain` holds the policy, the graph and one
pure `decide()`; `application` holds a single-threaded `tick()`; `adapters` holds the
only lock, the only thread, the only frame read and the only exit. The consequence
worth naming is that **the whole escalation chain is testable with a fake clock and
no threads at all**, which is why a thirty-second stall costs microseconds to assert.

**9. `ShutdownSignals` widens by one method rather than gaining a sibling port.**
`request()` sets the same latch a signal handler sets. A second port over a second
flag would let `Session.stop_requested()` stop seeing one of them, silently, with no
test failing. A watchdog-requested stop is recorded as `ShutdownReason.SIGNALLED` —
"something else asked" is accurate, and which something is in the incident.

## Consequences

- `WatchdogPolicy` refuses two orderings no single range check would catch: a stall
  threshold at or below the poll interval, and an escalation grace below it.
- A component that resumes after a confirmed stall still dies with the process, and
  `RUNTIME_WATCHDOG.md` says so under a heading rather than in a footnote.
- `tests/unit/test_watchdog.py` builds every transition from literals; no test in
  the subsystem sleeps.
- GLOBIN starts its first thread. It is non-daemon, waits on an `Event` rather than
  sleeping, and is disarmed before it is joined.
- One new exit code, `WATCHDOG_STALLED` (23), which no command returns.

## Alternatives Considered

**A timestamp-only heartbeat.** Simpler and one field smaller. Rejected: it cannot
distinguish a live loop inside a wedged call from real progress, which is the
failure most worth catching.

**A separate `suspect_millis` setting.** Rejected under
[`../CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md)'s warning that a
configuration model is where speculative fields accumulate. Nobody could defend a
value for it that was not "about one interval".

**A deadline measured from the request.** Rejected as above; it makes the guarantee
depend on the watchdog's own promptness.

**A separate `ShutdownRequest` port.** Better interface segregation, and rejected
for it: two names over one latch invites a second implementation with a second flag,
and that divergence would be silent.

**Cancelling the incident on a late beat.** Rejected: it produces a run whose
published evidence claims a stall the same run then denies.

**Putting the frame and thread bounds in configuration.** Rejected on the
`TRACEBACK_LIMIT` precedent. They bound a record's readability, which is a decision,
not a policy an operator has a basis to vary.

## Risks and Trade-offs

**The characteristic failure mode is a policy that is legal but useless.** The
validator refuses the degenerate orderings, but a `stall_millis` only slightly above
`interval_millis` is accepted and will declare stalls constantly under ordinary
scheduling jitter. **The observable signal** is repeated `watchdog.stall.confirmed`
records for components that are plainly running, and the fix is the operator's
rather than the code's.

**A second failure mode is the thread-confinement assumption being broken later.**
Nothing enforces that only one thread calls `tick()`; it is true because one adapter
owns it. **The observable signal** is a second caller appearing, at which point the
"exactly one incident" guarantee quietly stops holding — the correct response is to
restore confinement, not to add a lock, because a lock would make the invariant
depend on remembering to hold it.

**A third is that the deadline is unforgiving by design.** A component doing
legitimate long work without beating will be killed. The mitigation is
`Criticality.ADVISORY` and a truthful `stall_millis`, both of which put the decision
where the knowledge is.

## References

- [`../engineering/RUNTIME_WATCHDOG.md`](../engineering/RUNTIME_WATCHDOG.md) — the
  operator-facing description of everything decided here.
- [`../research/phase_025_sources.md`](../research/phase_025_sources.md) — S-06,
  S-08 and S-09 on frames, staleness and why `sys.exit` cannot end a process from a
  thread.
- [ADR-0034](0034-time-is-injected-and-internal-time-is-utc.md)
  — the clock discipline decision 3 applies.
- [ADR-0059](0059-the-mutable-runtime-tree-is-user-local-and-one-coordinator-is-proved-by-a-lock.md)
  — the shutdown latch decision 9 widens.
- [ADR-0064](0064-phase-025-widens-to-deliver-the-runtime-watchdog.md) — why this
  phase built it at all.

## Supersedes

None.

## Superseded By

None.
