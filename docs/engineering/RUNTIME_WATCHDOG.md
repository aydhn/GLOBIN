# Runtime Watchdog

How a running GLOBIN notices that it has stopped making progress, what it records
before it stops, and what happens when it will not stop on its own.

Phase 024 gave the process a way to answer *how am I doing*. This answers the
question a health surface cannot answer about itself: *is anything still asking*. A
process that has wedged does not report that it has — it reports nothing, and a
surface read only on request is silent in exactly the case that matters.

---

## The chain, in one line

Heartbeat → suspect → confirmed stall → evidence → graceful request → bounded
grace → termination.

Each arrow is a state transition in
[`src/globin/domain/watchdog.py`](../../src/globin/domain/watchdog.py), and the
whole chain is a pure function of a policy, a heartbeat snapshot and a monotonic
reading. That is what lets a thirty-second stall be tested in microseconds.

---

## Liveness is monotonic, and a heartbeat is a sequence

**Every elapsed quantity is measured on a monotonic clock.** Wall-clock time moves
when an operator corrects it, when the host resumes from sleep, and twice a year in
most of the world. A stall threshold compared against it would fire on a clock
correction and stay quiet across a suspend. The only wall-clock value in the
subsystem is an incident's `detected_at`, which exists so a human can find the
moment in a log and which nothing compares against anything.

**A heartbeat advances a counter rather than rewriting a timestamp.** Rewriting a
timestamp proves only that some thread reached the line that rewrites it, and a
component looping inside a wedged call can do that indefinitely. `beat()` increments
a sequence, so *still alive* and *still progressing* are different observations.

**Registration seeds a beat.** A component registered and never heard from is
measured by the same subtraction as everything else, so there is no `None` timestamp
anywhere and no special case for a component that has not started.

**Beating a name nobody registered raises.** A silent no-op would mean the component
an operator believes is watched is watched by nothing, and the watchdog would report
a healthy process for ever. It can only ever be a wiring mistake, and it fires on
the first beat.

Two criticalities are declared at registration:

| Criticality | What its silence means |
|---|---|
| `required` | A stall. Evidence, a request, and eventually a termination. |
| `advisory` | A warning, and nothing else. It can never end the process. |

This is `HealthCheckSpec.tolerates_unknown` applied to liveness — the tolerance is
declared once, visibly, rather than decided when it would be convenient.

---

## Suspect is not stalled

| State | Means | Does |
|---|---|---|
| `disabled` | Not armed, or switched off | Nothing |
| `starting` | Inside the start-up grace | Judges nothing |
| `healthy` | Every required component beat within one interval | Nothing |
| `suspect` | A required component missed one interval | One warning |
| `stalled` | It passed the stall threshold | Claims the incident |
| `capturing_evidence` | Gathering the post-mortem | Reads frames, writes a dump |
| `shutdown_requested` | The stop has been asked for | Runs the deadline |
| `escalating` | The deadline passed | Ends the process |

**`suspect` needs no threshold of its own**: it is "silent longer than one poll
interval", derived from a setting that already exists. A fourth duration would have
had to justify itself, and *we looked, and it had not moved since last time* is
already the natural meaning of a first warning.

**`capturing_evidence` describes the watchdog rather than the process**, and that is
why it exists. The collectors touch disk. A watchdog wedged writing evidence onto a
full disk would otherwise be published as `stalled` for ever while the process it
should have ended carried on.

### Recovery has exactly one inbound edge

Only `suspect → healthy`. Once a stall is confirmed the machine cannot return to
health, and that is structural rather than a guard: the transition table simply has
no such pair.

A component that resumes afterwards is **recorded and ignored** — a
`watchdog.late.progress` warning carrying its old and new sequence. It has already
missed whatever deadline mattered, and the process has already published a record
saying it stalled. A run whose evidence claims a stall the same run then denies is a
run nobody reads twice.

---

## Exactly one incident per stall

Guaranteed by the graph rather than by a counter. There is exactly one edge into
`stalled`, from `suspect`, and `suspect` is unreachable from any settled state.

The state machine is also **thread-confined**: only the watchdog thread ticks it, so
there is no race to prevent and no lock around it. Two things genuinely are shared,
and both live in the adapter — the heartbeat table behind one small lock, and the
stop latch, which is a monotone boolean that must *not* have one.

---

## Evidence

Best effort, bounded, and independently contained. One collector failing does not
stop the others; each failure becomes a sentence in the incident rather than an
exception, because the caller is already handling a failure.

| Source | What it gives |
|---|---|
| `faulthandler.dump_traceback` | A native all-thread traceback, written by C, into Phase 023's already-open fault file behind a marker line naming the incident |
| `sys._current_frames` | Bounded, sanitised Python frame summaries |
| `SystemThreadProbe` | The live thread inventory, reused from Phase 024 |

The bounds are fixed constants, not settings — 32 threads, 24 innermost frames
each, 64 KiB overall. They are chosen so a record stays readable, which is a
decision rather than a policy an operator has a basis to vary; `TRACEBACK_LIMIT` in
Phase 023 set the precedent. Frames are kept innermost-first because a hang is
described by where it is parked, not by how it got there.

### What the evidence deliberately does not contain

**No locals, ever.** `sys._current_frames` hands out live frame objects, and every
one has an `f_locals` holding the values a credential-reading function was working
with — not merely the name of the function reading them. The collector extracts
summaries with `traceback.extract_stack`, never passes a capture-locals option,
never calls `repr` on anything from a frame, and drops the mapping in the same call.

**No path that names a person.** Every frame's filename goes through
`relative_location`, the reduction Phase 024 already uses for allocation sites: a
path under the package becomes `globin/...`, one under the standard library becomes
`stdlib/...`, and anything else is reduced to its bare filename, *because a path
that could not be attributed is a path whose directories are somebody's private
business*.

**The watchdog's own thread is excluded**, or the evidence would be dominated by
the collector describing itself.

### Where it goes, and why that answers Phase 024

`state/watchdog.json` in the user-local runtime tree, published atomically.

Phase 024 refused to put stacks in the health surface, arguing that *a thread parked
inside a credential read would say so*. That objection is about **travel**: a health
snapshot goes into a support bundle and from there to whoever an operator sends it
to. A stall incident is a local post-mortem. It is deliberately **not** a bundle
candidate, and a contract test asserts that rather than trusting this paragraph.
What does reach the health snapshot is a `watchdog` summary of counts, state names
and component names — no path, no stack, no timestamp.

---

## Shutdown, and the bounded escalation

Ordered, and the order is the guarantee:

1. Claim the incident — one transition, unrepeatable.
2. Emit a critical structured record.
3. Capture evidence, bounded and contained.
4. Publish the incident. `StateStore.publish` fsyncs before it renames, so the
   evidence is durable **before** anybody is asked to stop.
5. `ShutdownSignals.request()` — the graceful ask.
6. Run the deadline.
7. Terminate.

**The deadline is measured from the stall, not from the request.** Otherwise a slow
evidence capture would postpone the end of the process indefinitely, and the
guarantee would depend on when the watchdog got round to asking politely. Measured
from the stall it is flat and assertable: a required component silent for
`stall_millis + escalate_millis` ends the run, whatever the watchdog was doing in
between.

### What happens when the main thread never polls

That is the whole point of the phase, and it needs no extra signal. Teardown runs
`Session.on_close` → `watchdog.stop()`. So if the deadline expires while the loop is
*still ticking*, nothing began unwinding — **the watchdog's own survival is the
proof that the graceful stop failed.**

### Why `os._exit`

`sys.exit` raises `SystemExit`, and the language reference is explicit that it *"will
only exit the process when called from the main thread"*. From the watchdog's thread
it would end that thread and leave the wedged process running — a silent failure of
the one mechanism that must not fail silently. `os.abort` goes through the C runtime
and on Windows can raise a modal abort dialog, which on an unattended host is the
hang the watchdog exists to end. `os._exit` runs no `atexit` handler, unwinds
nothing and waits on no lock, which is correct precisely because the reason this
path was reached is that something is holding one.

It is reached through the `ProcessTerminator` port and injected, so **no test ever
kills the runner**.

Exit code **23**, `WATCHDOG_STALLED` — the one value no GLOBIN command returns, so
a launcher seeing it knows the run did not choose its own ending.

---

## Configuration

Six settings, registered in
[`../CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md) and validated twice: once
by `as_config`, whose message names the document a value came from, and once by
`WatchdogPolicy`, because a policy that could not be honoured must not exist.

Two orderings are refused that no single range check would catch:

- **`stall_millis` at or below `interval_millis`.** A component examined one
  interval after beating has by definition been silent for one interval, so the
  watchdog would declare a stall on every tick.
- **`escalate_millis` below `interval_millis`.** The deadline would expire between
  two ticks and never be observed, so the effective grace would be whatever the next
  tick happened to be.

`watchdog.escalation_enabled` is the narrower of the two switches: turning it off
keeps the detection, the evidence and the graceful request, and stops only at the
termination. Evidence is still published either way — an operator who turned the
killing off wants to know what happened more, not less.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `ValidationError: 'x' is not monitored` on the first beat | The name passed to `beat()` does not match the one passed to `register()` |
| A stall is declared immediately and repeatedly | `stall_millis` is too close to `interval_millis`; the policy refuses the degenerate case but a value just above it is legal and noisy |
| `watchdog.late.progress` in the log and the process still ends | Working as designed — see *Recovery has exactly one inbound edge* |
| `watchdog.loop.failed` once, then silence | A tick raised. The protection is gone and the record says so; retrying would flood the log for ever |
| `watchdog.evidence.failed` with `stage=publish` | The runtime tree could not be written. The escalation continues, because the record exists to explain a termination that is happening anyway |
| No `watchdog` object in `diagnostics snapshot --json` | Expected today — see *Limitations* |

---

## Limitations

**Nothing starts a watchdog yet, and that is deliberate.** No current CLI command is
long-running, and starting a thread for a 200 ms command is waste. The subsystem is
wired to the Phase 022 lifecycle seam and exercised by tests; the long-lived process
that will own one is **Phase 257**. Until then the health snapshot's `watchdog` field
is `null` everywhere the CLI renders it, which is a true answer rather than a gap.

**A frame from a thread that is *not* stuck may already be stale.** The language
reference says so plainly: the stalled component's own stack is trustworthy because
that is the frozen case, but every other thread in a dump is a sample that may have
moved on. Read them as a hint about what the process was doing.

**`dump_traceback` cannot be time-bounded from the calling thread.** Reusing an
already-open handle removes the `open` and the `mkdir`, which is the strongest bound
available; a timer thread to enforce more would be building Phase 263's supervisor.

**Redaction matches field names, not free text.** A credential inside an exception
message or inside a component name an operator chose will be written. This is the
same limit `RUNTIME_DIAGNOSTICS.md` records, stated here rather than implied.

**This is not a supervisor.** Restarting a component, ordering a stop across
subsystems, classifying a failure, retrying, draining work in flight, or reading
`watchdog.json` back after a restart are Phases 262 to 268. Terminating a process is
not recovery — it is the considered refusal of it.
