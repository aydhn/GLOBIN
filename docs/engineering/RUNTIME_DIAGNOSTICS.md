# Runtime Diagnostics

How a running GLOBIN explains itself: where its records go, which faults it can
still report when nothing else works, and what it deliberately does not do.

This document owns the *runtime* half of observability — files, hooks, lifecycle
events. It does **not** own the record shape, the severity meanings or the
redaction list; [`../LOGGING_POLICY.md`](../LOGGING_POLICY.md) owns those and this
document does not restate them.

---

## What Phase 023 added, and what it did not

Phase 006 built the logging subsystem: a self-redacting record, a one-method
`LogSink` port, an immutable `Logger`, and a JSON-Lines stream sink. All of it was
correct and **nothing in the product called it**. `build_logger` had no production
caller, and the CLI printed with `print`.

So this phase did not build logging. It gave the logging that existed somewhere to
write, something to say, and the four hooks through which a fault arrives when no
`try` block is left.

| Added | Not added |
|---|---|
| A bounded rotating file sink in the runtime tree | A second record format — the envelope is unchanged |
| A lifecycle event vocabulary | Ambient correlation. [ADR-0026](../adr/0026-correlation-is-bound-explicitly-not-ambiently.md) stands |
| `sys.excepthook`, `threading.excepthook`, `sys.unraisablehook` | `logging` in GLOBIN's own call sites |
| `faulthandler`, pointed at its own file | POSIX signal registration — see below |
| A bridge for third-party `logging` records and Python warnings | A change to the warning *filters* |
| An asyncio handler, built and ready | An event loop to install it on |

---

## Where records go

Two destinations, one logger, one correlation id. A fan-out sink holds both, and
each element carries its own threshold — the arrangement
[`../LOGGING_POLICY.md`](../LOGGING_POLICY.md) describes when it explains why
filtering lives in a decorating sink rather than in the logger.

| Destination | What it is for | Threshold |
|---|---|---|
| `sys.stderr` | A human watching a command run | `logging.min_severity` |
| `<runtime root>/logs/globin.log` | What happened, after the fact | `logging.min_severity` |

**Console output never touches standard output.** Under `--json` the CLI promises
standard output carries JSON and nothing else, so a sink defaulting there would
break every machine consumer. `build_diagnostics` resolves `sys.stderr`, and an
integration test asserts standard output stays empty.

### The file sink flushes every record, and the stream sink does not

That difference is deliberate and is the one place these two sinks disagree.
`StreamLogSink` does not flush because its stream is line-buffered and flushed at
exit. The file sink exists **so that a process which dies badly leaves an
explanation behind**, and an explanation still sitting in a buffer when the
interpreter is killed is not one.

### Rotation, and why the bound is a type

`logs/` is the only area of the runtime tree that is *appended* to. Every other
area holds small documents published whole and atomically; a log is the one thing
GLOBIN writes that grows. [ADR-0059](../adr/0059-the-mutable-runtime-tree-is-user-local-and-one-coordinator-is-proved-by-a-lock.md)
named exactly that as the characteristic failure of adding a directory.

So the bound is a validated value type rather than a number passed around:

```text
ceiling = rotation_max_bytes x (rotation_backup_count + 1)
```

`RotationPolicy` refuses a size below 4 KiB or above 64 MiB, and a backup count
above 32. A policy that could not be honoured cannot be constructed, so no sink
has to refuse one it was handed. `ceiling_bytes()` states the worst case as a
number, because a reviewer asking "how large can this get" should not have to
multiply. At the defaults it is **8 MiB**.

Rotation closes the live file, shifts the backups from **oldest to newest**, then
opens a new one. Shifting the other way round loses the newest backup, which is the
one anybody would actually want. A backup count of zero means *rotate and discard*
— a real choice for a machine short of disk, not a disabled state.

---

## Lifecycle events

Event names are constants, so the set of things GLOBIN can report is enumerable
rather than discovered by reading log output. They live in
`globin.domain.diagnostics` and a contract test holds the code and this document
to each other.

| Event | When |
|---|---|
| `bootstrap.started` | A start-up began |
| `configuration.loaded` | Configuration resolved and validated |
| `runtime.paths.prepared` | The mutable tree exists and is writable |
| `instance.lock.acquired` | This process is the machine's one coordinator |
| `diagnostics.initialised` | Sinks open, hooks installed |
| `bootstrap.completed` | Every start-up gate measured |
| `application.ready` | Start-up passed; work may begin |
| `shutdown.requested` | A signal asked this process to stop |
| `shutdown.started` | Teardown began |
| `shutdown.completed` | Teardown finished |
| `diagnostics.stopped` | Hooks restored, sinks closed |
| `exception.uncaught` | Reached the top of the main thread |
| `exception.thread_uncaught` | Reached the top of a background thread |
| `exception.unraisable` | The interpreter could not propagate it at all |
| `exception.asyncio_uncaught` | An event loop reported it |
| `runtime.warning` | A Python warning, routed here |
| `faulthandler.enabled` | Native-fault tracebacks are armed |
| `dependency.record` | A library emitted a standard-library record |

This is **not** an audit-event taxonomy. Phase 281 owns the immutable event trail
and Phase 280 owns metrics; these are the names a start-up and a shutdown produce.

---

## The fault hooks

Three hooks are installed by the composition root, explicitly, and removed on the
way out. Nothing installs itself at import — `ENGINEERING_CONTRACT.md` invariant 5
forbids import-time work, and a module that grabbed `sys.excepthook` on import
would change the behaviour of any program that imported GLOBIN for any reason,
including a test collecting it.

**Each hook replaces the previous one and puts it back; it does not chain to it.**
The default `sys.excepthook` prints a traceback to standard error, and calling it
as well would produce two reports for one fault — one as JSON and one as prose,
with the prose landing in the stream `--json` promises is clean.

**An orderly exit is recorded, not mourned.** `SystemExit` and `KeyboardInterrupt`
are `INFO`, because `CRITICAL` means GLOBIN cannot do its job and being asked to
stop is not that. An operator who sees `CRITICAL` on every Ctrl-C stops reading it.

### The one place GLOBIN swallows an exception

A fault reporter catches broadly and reports to `stderr` if its own sink fails.
The reasoning is narrow enough to state: a hook runs when the process is already
failing, and an exception raised inside `sys.excepthook` is printed by the
interpreter and discarded — so it cannot propagate anywhere useful and can only
replace the report with a worse one. Invariant 23 forbids swallowing *silently*,
and this is not silent.

The same applies to formatting: an exception whose `__str__` raises, and an
unraisable fault whose object's `__repr__` raises, both still produce a report.
That is not defensive programming for its own sake — an unraisable exception very
often comes from a `__del__`, so the object being described is part-destroyed and
its `__repr__` is the code most likely to raise a second time.

---

## `faulthandler`

Enabled with its own file, `<runtime root>/logs/faults.txt`.

**The output is not JSON, deliberately.** A faulthandler traceback is written by C
code with no encoder involved, which is the entire reason it still works when the
interpreter can no longer run Python. It goes in its own file so that nothing
parsing the NDJSON log meets a line that is not a record.

**The handle must outlive the enabling.** `faulthandler.enable` records the file
descriptor and writes to it from a signal context, so the order is fixed: enable
then hold, disable then close, never the other way round.

**No signal registration.** `faulthandler.register` does not exist on Windows —
measured on the target host and recorded as S-07 in
[`../research/phase_023_sources.md`](../research/phase_023_sources.md). `enable`
covers what matters here: a segmentation fault or an abort from native code inside
a wheel.

---

## The standard-library bridge

GLOBIN's own call sites still do not use `logging`, and
`tests/architecture/test_logging_discipline.py` fails if that changes. What the
bridge adds is the thing `adapters/observability.py` anticipated in Phase 006:

> When a dependency first emits standard-library records, a second `LogSink`
> implementation bridges them; the port is what makes that an addition rather
> than a rewrite.

Phase 021 adopted `numpy` and `pandas`, so that dependency now exists. Python's own
warnings arrive by the same road: `logging.captureWarnings` routes them to the
`py.warnings` logger, which this handler receives — one bridge, one place to remove.

**The warning filters are untouched.** Deciding which warnings are produced is a
different question from deciding where they go, and the suite's
`filterwarnings = ["error"]` is deliberate. A phase that relaxed the filters to
make its own output tidier would silently disarm it.

Severity needs no mapping table: the standard library's level numbers are GLOBIN's
severity values, which `Severity`'s docstring called a deliberate borrowing. The
bridge still rounds *down* to the nearest defined severity rather than calling
`Severity(levelno)`, because libraries invent intermediate levels and an exact
lookup would raise inside the logging system rather than record the message.

---

## Secrets

**Never pass a secret to a log message or a structured field.** That is the rule,
and redaction is defence in depth behind it — not permission to rely on.

Redaction is by field **name**, applied while the record is constructed, so no sink
can leak by forgetting to call something. The list and the mechanism are
[`../LOGGING_POLICY.md`](../LOGGING_POLICY.md)'s.

### What that does not cover, stated plainly

A secret interpolated into a **string** is past every rule about names. The clearest
case is an exception message: if a credential is inside `str(exception)`, it reaches
`exception_message` and is written.

This is not solved here, and pretending otherwise would be worse than saying so.
GLOBIN holds no credentials at all today — `NoSecretsRequired` means the
`secrets.required` check passes vacuously — so there is no known secret *value* to
scan for, and scanning for anything that merely looks like one is a heuristic that
would mangle legitimate diagnostics. When Phase 028 gives GLOBIN a secret store,
value-based scrubbing becomes implementable because there will finally be a set of
values to scrub. Until then the defence is the rule at the top of this section.

---

## Order

Start-up opens files before installing hooks; shutdown removes hooks before closing
files. A hook that fired between the two would have nowhere to write; a hook still
installed after its sink closed would raise inside the interpreter's own error path.

Shutdown is registered through `Session.on_close`, which runs **every** cleanup even
when an earlier one raised — so each step is independently safe and idempotent
rather than relying on the ones before it having worked. Starting twice installs one
set of hooks; stopping twice is a no-op.

**Nothing flushes inside a signal handler.** `PlatformShutdownSignals` sets a flag
and returns, which is Phase 022's contract and is unchanged.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| No `logs/` directory | The runtime tree was never prepared; run `globin doctor` |
| `the log sink was not opened` | `RuntimeDiagnostics.start()` was not called — a deliberate error rather than a silent no-op, because a silent one means every record went nowhere and nothing said so |
| Log stops growing, backups unchanged | `rotation_backup_count` is `0`, which discards rather than keeps |
| `ConfigurationError` naming a rotation setting | The value is outside its bound; the message names the document it came from |
| Records missing below a severity | `logging.min_severity` is raised; it applies to both destinations |
| A warning appears as `runtime.warning` | Expected — warnings are captured, not suppressed |

### Verifying

```bash
.venv\Scripts\python.exe -m pytest -q -m "not external"
```

The behaviour above is asserted by `tests/unit/test_diagnostics.py`,
`tests/integration/test_diagnostics_end_to_end.py` and
`tests/architecture/test_logging_discipline.py`.

---

## Related documents

- [`../LOGGING_POLICY.md`](../LOGGING_POLICY.md) — the record shape, severity meanings and redaction list
- [`RUNTIME_FILESYSTEM.md`](RUNTIME_FILESYSTEM.md) — the five areas, and why `logs/` is bounded
- [`BOOTSTRAP.md`](BOOTSTRAP.md) — the start-up sequence these events describe
- [`../CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md) — the three logging settings
- [`../adr/0060-gpu-capability-is-detected-and-the-runtime-explains-itself.md`](../adr/0060-gpu-capability-is-detected-and-the-runtime-explains-itself.md) — the decisions
- [`../research/phase_023_sources.md`](../research/phase_023_sources.md) — what was measured
