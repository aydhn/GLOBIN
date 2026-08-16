# The runtime filesystem and the process lifecycle

Where a running GLOBIN keeps state, how it guarantees one coordinator per machine,
and what it does and does not promise when something goes wrong.

**This reaches no network.** No exchange is contacted, no credential is read and
no order is placed. What is here is local machinery: a directory tree, an atomic
write, an operating-system lock and an orderly shutdown.

The decisions are in
[ADR-0059](../adr/0059-the-mutable-runtime-tree-is-user-local-and-one-coordinator-is-proved-by-a-lock.md),
and [ADR-0057](../adr/0057-phase-022-widens-to-deliver-the-runtime-filesystem-and-lifecycle.md)
records that delivering this in Phase 022 was the programme's sixth scope
amendment and which of ADR-0021's four criteria it failed. This document is how to
use what those decided.

---

## Two roots, and they answer different questions

| Tree | Holds | Lives |
|---|---|---|
| `.globin/` | Evidence written by verification tooling **about this repository** — `runtime`, `lock`, `drift`, `wheels`, `stack`, `bootstrap` | Inside the checkout, Git-ignored, regenerated per clone |
| The **runtime root** | Mutable state a **running GLOBIN** keeps | Outside the checkout, under the platform's per-user application data area |

Phase 021 declared `state`, `cache` and `logs` under `.globin/` as *reservations*
that nothing created. Phase 022 did not move them; it separated two things that
were being named as one. The evidence tree is about a repository and is read by
CI. The runtime tree is about a machine.

**Where the runtime root is.** Under the directory Windows documents as
`FOLDERID_LocalAppData` — the Known Folder whose default path Microsoft gives as
`%LOCALAPPDATA%` (`%USERPROFILE%\AppData\Local`) — in a `GLOBIN` namespace.

Reading that environment name is a **platform lookup**, not a configuration
source. [`../CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md) defers
environment-variable resolution to Phase 027, and this phase adds no new
`os.getenv` call to the configuration path: the adapter is handed a mapping. When
the variable is absent GLOBIN **refuses to start**. It does not fall back to the
home directory, the working directory or a guess, because a machine-wide lock
whose location depended on how the process was started would guard nothing.

Nothing published anywhere records that path. It lives under a user profile, and a
user profile directory names its owner, so every record carries a fingerprint
instead.

---

## The five areas

```text
<runtime root>/
├── state/    small, long-lived operational metadata
├── cache/    reproducible data
├── run/      the live instance's lock and metadata
├── tmp/      one directory per run, owned by that run
└── logs/     bounded diagnostic records — the only area appended to
```

The difference between them is a promise about deletion.

| Area | Holds | Safe to delete |
|---|---|---|
| `state/` | `lifecycle.json` — what the last run did | Yes. GLOBIN starts clean and loses only diagnostics |
| `cache/` | Anything GLOBIN can regenerate | **Always.** Deleting it must change no answer; a component that cannot honour that needs `state/` |
| `run/` | `instance.lock`, `instance.json` | Only while nothing is running |
| `tmp/` | One directory per run id | Between runs |
| `logs/` | `globin.log` and its rotated backups, `faults.txt` | Yes. Nothing GLOBIN decides reads from here |

### Why `logs/` is separate, and why it is bounded

Phase 023 added the fifth area, and it is the only one that is **appended to**.
Every other area holds small documents published whole through `publish`, which
replaces a file atomically; a log is the one thing GLOBIN writes that grows.

That makes it precisely the risk ADR-0059 named about adding a directory — "a
later phase writing something large into `state/` because the directory was
already there". Keeping it out of `state/` is what lets the bound apply to the
growing thing and not to the small ones. The bound itself is a validated value
type rather than a number passed around: `RotationPolicy` refuses a size below
4 KiB or above 64 MiB and a backup count above 32, so a policy that could not be
honoured cannot be constructed, and `ceiling_bytes()` states the worst case as a
number rather than leaving a reviewer to multiply.

`faults.txt` is **not** JSON, deliberately. `faulthandler` writes a native
traceback from C with no encoder involved, which is the entire reason it still
works when the interpreter can no longer run Python — so it goes in its own file
rather than putting a non-record line in an NDJSON log everything else is
entitled to parse.

### What may never go there

Absolute, and not a matter of taste:

- credentials or plaintext secrets, Credential Manager or DPAPI material, `.env`
  contents, API keys, exchange tokens — Phase 028 decides where a secret lives
- market-data history, order or trade ledgers — Phases 097-112
- model artefacts, Parquet datasets — Phase 190 and the data-platform band

The tree defined here is **small, non-secret and disposable**, and everything else
in the design assumes all three. ADR-0059 records the characteristic failure: a
later phase writing something large, or something secret, into `state/` because
the directory was already there. Nothing but this document and review prevents it —
no gate can tell a large file from a small one.

**A layout cannot escape its own root.** Every segment is validated at
construction: `..`, a path separator, a drive letter and an empty string are all
refused, so a tree that could leave its root cannot be built. Every joined child
is checked again where it is used.

### The one thing Phase 024 added, and why it is in `cache/`

A support bundle — the redacted archive `globin diagnostics bundle` produces — is
published to `cache/support/globin-support.zip`. **No sixth area was added**, and
`cache/` rather than `state/` is a decision rather than convenience.

`state/` holds the small documents a run publishes atomically *about itself*, and
a reader must never observe one half-written. A bundle is none of those things: it
is a bounded, reproducible artefact an operator asked for and may delete without
breaking anything, which is what `cache/` is for. It is still published atomically
— built under a `.partial` name beside its destination, validated, hashed, then
`os.replace`d — because an incomplete archive appearing under the name somebody is
about to send is its own kind of failure.

It is bounded twice over: by `diagnostics.bundle_archive_bytes`, and by the rule
above that nothing large lives in this tree. The bundle's own contents are governed
by [`SUPPORT_BUNDLE.md`](SUPPORT_BUNDLE.md), which is stricter than this document
because the file leaves the machine.

---

## Publishing state

Every small document is published atomically or not at all:

1. write to a uniquely-named temporary file **in the destination's own directory**
2. serialise deterministically — sorted keys, compact separators, ASCII,
   `allow_nan=False`
3. `flush()`
4. `os.fsync()` the descriptor
5. close
6. `os.replace()` over the destination

Three properties follow, and each is tested by breaking exactly one stage:

- **A reader never observes a truncated document.**
- **A failed write leaves the previous document intact.**
- A temporary artefact is cleaned up on the failure path, and failing to clean it
  up never replaces the fault an operator has to act on.

`os.replace` is used rather than `Path.rename` because it overwrites an existing
destination, which every republication needs and which `rename` refuses on
Windows. The temporary file may not live in the platform temporary directory: a
rename is only atomic within one filesystem, and putting it elsewhere would
silently turn the atomic step into a copy.

`NaN` and `Infinity` are refused rather than written. They are not JSON, every
standard reader rejects them, and writing one would turn a numeric mistake into a
document only Python could read back.

---

## One coordinator per machine

**The presence of `instance.lock` is never evidence that GLOBIN is running.**

This is the rule the whole design turns on. A process that crashes, is killed or
loses power leaves its lock file behind, so a file on disk proves GLOBIN once ran
and nothing else.

Ownership is decided by the result of a non-blocking `msvcrt.locking` acquisition
and by nothing else. The operating system releases the region when the holding
process ends — measured on the target host, and pinned by
`tests/integration/test_instance_lock_subprocess.py`, which kills a holder with
`os._exit` so that no `finally` and no `atexit` runs, and then watches the next
process acquire.

Three consequences, each a rule:

- A leftover lock file **must not** block a start-up. If the lock can be taken, it
  is taken.
- A stale lock file is **never** deleted on a guess. No PID comparison, no
  timestamp heuristic, and under no circumstances is a process belonging to
  another PID signalled or killed.
- A second coordinator that cannot acquire fails **closed**, with exit code `20`,
  and changes nothing the holder owns — the lock is taken before a single byte is
  written.

**The lock is narrow on purpose.** It guards one top-level coordinator against
being started twice. It is not a mutex for the workers of Phase 257 onwards or the
child processes of Phase 289 onwards, and it cannot correctly become one: it is a
whole-application lock, not a resource lock.

**`globin doctor` does not take it.** A read-only diagnostic that held the
production lock would refuse to run beside a running GLOBIN, which is exactly when
somebody wants to run it. It acquires and releases immediately, and its summary
says the check was a capability probe.

---

## Starting and stopping

```text
bootstrap checks pass  →  RuntimeContext exists
  → take the coordinator lock          nothing is written before this
  → install signal handlers            only signals this platform has
  → register the atexit net            best effort, nothing rests on it
  → claim this run's tmp directory
  → publish run/instance.json
  → publish state/lifecycle.json       status: running
  → APPLICATION RUNS
  → publish state/lifecycle.json       status: stopped, with a reason
  → remove this run's tmp directory
  → clear run/instance.json
  → release the lock
```

**Teardown reaches every step even if an earlier one failed.** A shutdown that
abandoned the rest because one step raised would leave exactly the debris it
exists to remove, so failures are collected and reported together as
`ShutdownIncompleteError` at the end. The application's own cleanup callbacks run
first and in reverse registration order, and every one of them runs however the
ones before it went.

### Signals

`SIGINT`, `SIGTERM`, and `SIGBREAK` where the running Python exposes it —
guarded by `hasattr` rather than by a platform string, because `signal.signal`
raises `ValueError` on Windows for anything outside its seven accepted signals and
a start-up that fell over installing its own shutdown path would be failing for
the least useful possible reason.

**A handler sets a flag and returns.** No I/O, no lock, no cleanup. Python runs a
handler on the main thread at a bytecode boundary and its documentation warns
explicitly against synchronisation primitives inside one, so the ordinary control
flow reads the flag and does the work.

### What is guaranteed, and what is not

| Ending | Lifecycle record | Lock | Temporary tree |
|---|---|---|---|
| Normal return | Closed, `completed` | Released | Removed |
| `SIGINT` / `SIGTERM` / `SIGBREAK` | Closed, `signalled` | Released | Removed |
| `KeyboardInterrupt` | Closed, `interrupted` | Released | Removed |
| Unhandled exception | Closed, `failed` | Released | Removed |
| `sys.exit` without unwinding | Closed by the `atexit` net, `failed` | Released | **Left behind** |
| Hard kill, power loss | **Left open** | Released by the OS | **Left behind** |

**`atexit` is a net, not a guarantee.** Python's documentation is explicit that it
does not run when a process is killed by a signal it does not handle, on a fatal
internal error, or on `os._exit` — which are exactly the cases crash safety is
about. Nothing rests on it, and it reads the record before writing so a run that
shut down properly is not overwritten by its own safety net.

**What makes a crash survivable is atomic publication, not cleanup running.**
Whatever was last written is complete and readable, whether or not anything got to
run afterwards.

### The previous run

If the last lifecycle record was never closed, the next start-up reports
`state.previous_run` as a **warning**: *the previous run may have terminated
uncleanly*. It does not refuse, and it does not conclude that a process is
running — that question is answered by the lock alone.

This is bootstrap evidence for an operator. It is not crash recovery (Phase 267)
and emphatically not trading reconciliation (Phase 095): nothing is resumed,
repaired or replayed.

---

## Reading a failure

The four checks this phase adds to `globin doctor` and `globin bootstrap check`:

| Check | Exit code | Means | First move |
|---|---:|---|---|
| `paths.boundary` | 16 | The runtime root could not be resolved, or an area escapes it | Read the message; usually `%LOCALAPPDATA%` is unset or an area exists as a file |
| `state.persistence` | 21 | A document could not be written, replaced and removed | Make the runtime state directory writable |
| `state.previous_run` | 19 | The lifecycle record is unreadable | Delete it. It is diagnostic evidence and nothing depends on it |
| `instance.lock` | 20 | Another coordinator holds the lock | Stop the running GLOBIN. **Do not delete the lock file** — it is not what decides ownership, and removing it releases nothing |

Deleting the runtime tree entirely is safe when nothing is running, and is the
blunt fix for anything else here.

---

## What this does not decide

Named so that silence does not read as a gap. Each of these is a phase whose work
this deliberately stops short of.

| Question | Phase |
|---|---|
| Where configuration files live, and what a profile is | 026 |
| Which sources set a value, and how environment variables fit | 027 |
| Where a secret is stored and how it is supplied | 028 |
| The wider preflight health-check suite | 030 |
| The long-lived process that owns and supervises subsystems | 257 |
| Starting and stopping subsystems in dependency order | 262 |
| Detecting and recovering a hung or dead component | 263 |
| Persisting scheduling and subsystem state across restarts | 266 |
| Recovering coherently from unexpected termination | 267 |
| Draining work in flight without abandoning it | 268 |
| Surviving sleep, updates and session changes | 270 |

Eight of those own part of what this phase built, which is what made it an
amendment rather than ordinary work. ADR-0057 records that, and what it cost.
