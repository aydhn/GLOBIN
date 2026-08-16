# Runtime Health

How a running GLOBIN reports on its own condition, and what each answer means.

[`BOOTSTRAP.md`](BOOTSTRAP.md) answers *may this process start*. This answers the
different question *how is it doing now*. A bootstrap check runs once, before
anything exists, and its failure means refuse to start. A health check runs against
a process that is already running, may be asked repeatedly, and its failure means
something an operator should look at — not necessarily something that should stop
the machine.

```bash
.venv\Scripts\globin.exe diagnostics snapshot
```

```bash
.venv\Scripts\globin.exe diagnostics snapshot --json
```

Under `--json` standard output carries the document and nothing else; the human
table and every log record go to standard error.

---

## The three states, and the rule that produces them

| State | Meaning |
|---|---|
| `healthy` | Every mandatory check passed |
| `degraded` | Something warned, or something was unmeasurable that should not have been |
| `unhealthy` | At least one check failed |

The reduction is in `globin.domain.health.aggregate_state` and is deliberately
**tolerant of a predicted unmeasurability**:

1. Any `fail` → `unhealthy`. Nothing forgives a failure.
2. Otherwise any `warn` → `degraded`.
3. Otherwise an `unknown` on a check the registry does **not** mark
   `tolerates_unknown` → `degraded`.
4. Otherwise `healthy`.

**Step 3 is the interesting one, and it exists because of a real host.** The CI
`quality` job installs the development toolchain and never builds `.venv`, so
`psutil` is absent there on every run and four process checks report `unknown`
every time; memory tracing is off by default, so a fifth does too. Under a rule
treating every `unknown` as bad news, that host would report `degraded` forever —
and a signal that is always amber is a signal nobody reads, which costs more than
the strictness buys.

`tolerates_unknown` is where a check declares, in the registry and in advance,
that its silence is an expected state of a healthy system. It is the same bargain
[`gpu-contract.toml`](gpu-contract.toml) strikes with `absence_means`: absence is
acceptable when somebody wrote down what it would mean.

**Forgiving it in the verdict does not hide it.** Every unmeasured check is still
in the results with its reason code, `unmeasurable()` counts them regardless, and
the human rendering prints the list. The characteristic failure of this design is
a genuinely required probe being marked tolerant to quieten a noisy host, and the
observable signal is a registry entry whose tolerance nobody can explain.

---

## A number that was not measured is never zero

`Availability` is the reason this surface can be trusted. Four words, and they are
not synonyms:

| Availability | Meaning | Fixable by |
|---|---|---|
| `measured` | A value was read | — |
| `unavailable` | Nothing here could answer, but something could be made to | Installing the library |
| `unsupported` | This platform has no such counter | Nothing |
| `denied` | The operating system refused | Changing privileges |

A dashboard showing 0% memory used because nothing could read it looks exactly
like a dashboard showing a healthy process, and the second is a conclusion nobody
drew. Reporting `0` for a counter Windows does not expose, or for a library that
is not installed, is the failure this whole model is shaped to prevent.

**No instantaneous CPU percentage.** psutil documents that the first
`cpu_percent` call on a process returns a meaningless `0.0`, because a percentage
is a ratio over an interval and the first call has no earlier reading to form one
with. A command that takes one measurement and exits has no interval, so
cumulative CPU *times* are reported instead and the percentage is `unavailable`
with the reason `HEALTH_CPU_NOT_SAMPLED`.

---

## The checks

Eighteen, in a fixed order, cheapest first. The order is part of the contract: two
snapshots of the same process must serialise identically, so a registry that
iterated a set would make the document — and therefore its digest — differ between
runs for no reason anybody could act on.

| Group | Checks |
|---|---|
| `runtime` | `runtime.identity`, `runtime.uptime`, `runtime.healthy` |
| `platform` | `platform.interpreter` |
| `process` | `process.identity`, `process.memory`, `process.cpu`, `process.threads`, `process.handles` |
| `host` | `host.cpu`, `host.memory`, `host.disk` |
| `paths` | `paths.present`, `paths.writable`, `paths.boundary` |
| `instance` | `instance.lock` |
| `logging` | `logging.state` |
| `memory` | `memory.tracing` |

**A check that raises does not take the snapshot with it.** The exception becomes
an `unknown` result carrying `HEALTH_CHECK_RAISED`, and is reported through the
Phase 023 sinks with its type attached. That satisfies
[`ENGINEERING_CONTRACT.md`](ENGINEERING_CONTRACT.md) invariant 23 rather than
dodging it — nothing is discarded — and it refuses the alternative, where a thread
counter throwing means an operator investigating a full disk learns nothing.

Only the exception's **type** is recorded. Its message and traceback are not: a
third-party exception's text is exactly where a credential ends up, and redaction
matches field names rather than free text.

---

## Uptime is monotonic

Uptime is the difference between two readings of
`globin.ports.clock.MonotonicClock`, never a subtraction of wall-clock instants.
A manual correction, a daylight-saving transition or an NTP slew cannot therefore
produce a negative or a wildly wrong uptime. The wall clock appears in a snapshot
only as `generated_at`, which is what a human reads.

---

## Memory tracing is opt-in, and the default is load-bearing

`tracemalloc` costs the whole process on every allocation, in every thread, until
it is switched off. A runtime that enabled it because the setting existed would be
paying a profiler's price to populate a diagnostic nobody asked for.

```bash
.venv\Scripts\globin.exe diagnostics memory
```

`memory` is a separate verb rather than a flag on `snapshot` because it does
something `snapshot` does not. A flag invites somebody to add it to a script that
runs every minute; a verb reads like the deliberate act it is. The probe also
refuses to stop a tracer it did not start, so taking a snapshot cannot silently
disable tracing an operator enabled for their own reasons.

Allocation sites are bounded, deterministically ordered and **path-sanitised**:
a traceback names absolute paths, and on this host every one of them begins with a
user profile directory, which names a person. What a reader needs is which module
is allocating, and that survives the conversion.

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | `healthy` |
| `1` | `unhealthy` |
| `3` | `degraded` |
| `22` | No snapshot could be produced at all |

The first three are the words every gate under `tools/` already speaks, so a
script that branches on one command branches on this one. `22` is separate because
*the process is unhealthy* and *nobody could tell* are different facts, and
collapsing them would hide the second from the consumer that most needs it. The
full table is in [`BOOTSTRAP.md`](BOOTSTRAP.md).

---

## Thresholds

Every bound is a typed setting in
[`CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md)'s `diagnostics` section,
never a literal at a comparison. Two are checked against each other:
`disk_warning_bytes` must be strictly above `minimum_free_bytes`, or the check can
never warn — it fails first, and the warning band has silently zero width.

**No new environment variable was added.** ADR-0057 and ADR-0060 both hold that
line; Phase 027 owns environment resolution, and settling its question early by
reading one here is the trap those records already named.

---

## What this does not do

- **No metrics, no exporter, no daemon.** Phases 280 and 315 own those. Nothing
  runs in the background and nothing counts anything over time.
- **No network of any kind.** No exchange is contacted, no credential is read.
- **No thread stacks.** Phase 023's `faulthandler` already writes native
  tracebacks, deliberately, into a file that is not the log.
- **No retention policy.** Phase 282 owns what an operator must keep and why.
