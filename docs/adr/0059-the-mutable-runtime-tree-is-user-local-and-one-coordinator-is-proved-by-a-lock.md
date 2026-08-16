# ADR-0059 — The mutable runtime tree is user-local, its state is published atomically, and one coordinator is proved by a lock rather than by a file

## Status

Accepted — Phase 022.

**Date:** 2026-08-16

## Context

[ADR-0056](0056-phase-021-widens-to-deliver-the-application-bootstrap.md) built a
bootstrap that decides whether a process may start and assembles a
`RuntimeContext` when it may. It stopped there, deliberately: `RuntimePaths`
declares `state`, `cache` and `logs` roots which that record is explicit are
*reservations* — names written down so the shape is agreed, with nothing creating
them and nothing writing into them.

So a GLOBIN process that has been told it may start has three gaps beneath it.
It has nowhere defined to keep state that outlives a run. It has no way to know
whether another GLOBIN is already running, which on a single-machine system with
one set of local resources is the difference between one coordinator and two
fighting. And it has no defined way to stop: no signal handling, no ordered
teardown, and no record of whether the last run ended or died.

There is a fourth gap, smaller and sharper. Phase 021's evidence writer publishes
with `Path.write_text`, which truncates the destination and then writes. A
process killed between those two steps leaves a truncated manifest, and the
reader — correctly — refuses it. A crash therefore turns into a second, unrelated
failure the next time anybody looks.

`docs/engineering/RUNTIME_BASELINE.md` and
[ADR-0050](0050-the-runtime-is-a-declared-contract-and-venv-is-its-only-environment.md)
constrain what may be touched: nothing outside the repository except `.venv`, and
no registry, PATH or execution-policy edits. That constraint was written about
*verification tooling*. This record is the first time the **application** needs
somewhere outside the checkout to write, and the distinction has to be made
explicitly rather than by silence.

## Decision

### There are two roots, and they answer different questions

`.globin/` inside the repository stays exactly what it already is: evidence
written by verification tooling *about this repository* — `.globin/runtime`,
`.globin/lock`, `.globin/drift`, `.globin/bootstrap`, `.globin/stack`. It is
regenerated per checkout, read by CI, and ignored by Git.

**Mutable application state moves to a user-local root** under the Windows Local
Application Data area, in a GLOBIN namespace. This is not a reversal of Phase
021: those three entries were reservations nothing had created, and this
separates two things that were being named as one.

| Directory | Holds | May be deleted |
|---|---|---|
| `state/` | Small, long-lived operational metadata: the lifecycle record | Yes — GLOBIN starts clean, losing only diagnostics |
| `cache/` | Reproducible data GLOBIN can regenerate | Yes, always, by definition |
| `run/` | Live-instance files: the coordinator lock and instance metadata | Only while nothing is running |
| `tmp/` | One subdirectory per run, owned by that run | Yes, between runs |

**What may never go there**, and the rule is absolute: credentials or plaintext
secrets, Credential Manager or DPAPI material, `.env` contents, API keys, exchange
tokens, market-data history, order or trade ledgers, model artefacts and Parquet
datasets. Those belong to Phases 028, 097-112 and 190, each of which decides its
own location. The tree defined here is small, non-secret and disposable, and
`docs/engineering/RUNTIME_FILESYSTEM.md` says so where an operator will read it.

**The root is resolved once, canonicalised, and every child is checked against
it.** Traversal segments, an absolute child that would escape, a file where a
directory belongs and a directory where a file belongs are all refused before
anything is created. No hard-coded user name, no `C:\Users\<name>`, no repository
path and no working directory participates in the resolution.

**Reading `LOCALAPPDATA` is a platform lookup, not a configuration source, and
the distinction is load-bearing.** `docs/CONFIGURATION_POLICY.md` defers
environment-variable *resolution* to Phase 027, and this phase adds no new
`os.getenv` call to the configuration path. The adapter is handed an environment
mapping rather than reading the process's own, so a test substitutes one without
touching global state and the seam Phase 027 will use already exists. When the
variable is absent the adapter **refuses**; it does not fall back to the home
directory, the working directory or a guess.

### A declared path is a string; a resolved path never reaches the domain

`docs/architecture/dependency-rules.toml` lists `pathlib` among the I/O-capable
modules and the domain may import none of them. The `pathlib.Path`-typed layout
therefore lives in the adapters layer, and the domain declares relative segments
and publishes `RecordedPath`. This is ADR-0056's rule applied unchanged.
Amending the layer contract to let a `Path` into the domain was considered and
refused: it would make the domain able to open a file, for a typing convenience.

`msvcrt` and `atexit` join `[io] capable_modules`. Both reach outside the
process — one takes an OS lock, the other registers an interpreter-exit hook —
and the list is the observable signal that a layer has grown such a capability.
This *tightens* the contract rather than loosening it.

### A lock file's existence is never evidence that an instance is running

This is the decision the whole locking design turns on. A process that crashes,
is killed, or loses power leaves its lock file behind; a file on disk therefore
proves that GLOBIN once ran, and nothing else.

**Ownership is decided by the result of a non-blocking acquisition and by nothing
else.** `msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)` was measured on the target host
before this was written: while one process holds the region, a second process
attempting it receives `PermissionError` with `errno 13`, and after the first
unlocks and closes, a third acquires immediately. That is a genuine cross-process
lock released by the operating system when the holding process dies, which is
what makes a stale file harmless.

Three consequences follow, and each is a rule:

- A leftover lock file **must not** block a start-up. If the lock can be taken,
  it is taken.
- A stale lock file is **never** deleted on the strength of a guess. No PID
  comparison, no timestamp heuristic, and under no circumstances is a process
  belonging to another PID signalled or killed.
- A second coordinator that cannot acquire fails **closed**, with its own exit
  code, and changes nothing the holder owns.

**The lock is narrow on purpose.** It guards one top-level coordinator against
being started twice. It is not a general mutex for the workers of Phase 257
onwards or the child processes of Phase 289 onwards, and it cannot correctly
become one — it is a whole-application lock, not a resource lock.

**A read-only command does not take it.** `globin doctor` probes the capability by
acquiring and releasing immediately, and says in its summary that this is a
probe rather than ownership. A diagnostic that held the production lock would
make `doctor` refuse to run beside a running GLOBIN, which is a read-only command
breaking the thing it was asked to inspect.

### A small state document is published atomically or not at all

Write to a uniquely-named temporary file **in the destination's own directory**,
serialise deterministically, `flush()`, `os.fsync()` the descriptor, close, then
`os.replace()`. `os.replace` is atomic when both paths are on one filesystem,
which is why the temporary file may not live in the platform temporary directory;
`Path.rename` is not atomic over an existing file on Windows, which is why it is
not used. `tools/quality/workflow/gate.py` already publishes this way, and this
generalises that rather than inventing a second mechanism.

Three properties are required of it. A reader must never observe a truncated
document. A failed write must leave the previous document intact. A temporary
artefact is cleaned up on the failure path on a best-effort basis, and failing to
clean it up never masks the original error.

Serialisation is the repository's canonical deterministic JSON — sorted keys,
compact separators, ASCII — with **`allow_nan=False`**, so `NaN` and `Infinity`,
which are not JSON, are refused rather than written as tokens no standard reader
accepts. Nothing that passes through this writer may be a secret.

### Cleanup is `try`/`finally`; `atexit` is a net, never a guarantee

Teardown order is fixed: stop accepting new work, run application cleanup, publish
the clean lifecycle record, remove this run's own temporary tree, clear the
instance metadata, release the lock, close handles.

`atexit` runs on normal interpreter termination. It does not run on `SIGKILL`, a
Task Manager termination, or a power loss. It is registered as a best-effort
fallback, and no correctness property rests on it. **Crash safety comes from
atomic publication, not from cleanup running** — which is why the previous
paragraph matters more than this one.

A signal handler sets an intent flag and returns. It performs no I/O, takes no
lock and runs no business logic; the ordinary control flow reaches a cleanup
point and does the work. Handlers are registered only for signals the running
Python actually exposes — `SIGINT` and `SIGTERM` always, `SIGBREAK` where
present, which on this host it is.

**A recursive delete re-verifies its target.** Before removing a run's temporary
tree, the resolved target is checked to be strictly beneath the canonical `tmp`
root. The runtime root, `state/` and `cache/` cannot be reached by that path.

### An unclean previous run is a diagnostic, not an inference

If the last lifecycle record was never closed, the next start-up may report that
the previous run may have terminated uncleanly. It **may not** conclude from that
record that a process is running — that question is answered by the lock alone.
This is bootstrap evidence for an operator; it is not trading reconciliation,
which is Phase 095, and it resumes, repairs and replays nothing.

## Consequences

GLOBIN now writes outside its own checkout for the first time. The property
"GLOBIN touches nothing outside the repository" is gone, and it was worth
something — it made the blast radius of a bug trivially bounded. What replaces it
is narrower and written down: one named tree, no secrets, no bulk data, and safe
to delete in its entirety.

Two checkouts on one machine now share one runtime root and one coordinator lock.
That is correct — they are one machine's GLOBIN — but it means a developer
running two working copies will find the second refusing to start, and the
message has to say why.

Every future component that wants durable state must ask which of the four
directories it belongs in, and `cache/` carries a real obligation: deleting it
must not change any answer. A component that cannot honour that needs `state/`,
and `state/` is for small documents.

The exit-code contract grows. ADR-0056 noted that adding a code is cheap and
changing one is not; this adds three at the top of the range and changes none.

Nothing here is a network capability, a credential store or a scheduler, and the
eight phases that own the larger versions of this work are now each slightly
smaller — recorded in
[ADR-0057](0057-phase-022-widens-to-deliver-the-runtime-filesystem-and-lifecycle.md)
rather than here.

## Alternatives Considered

**Keep everything repository-relative and add `run/` and `tmp/` to
`RuntimePaths`.** The smallest change, and it preserves the "nothing outside the
checkout" property. Rejected because the working directory would then decide
where a running system keeps its state — the ambiguity Phase 021 spent a bounded
upward root search removing — and because two checkouts would each hold their own
lock, so neither would see the other and the single-instance guarantee would be
worth nothing.

**Move `.globin/` wholesale to the user-local root, leaving one root.**
Superficially tidier. Rejected because the evidence under `.globin/` is *about a
repository*: it is read by CI, regenerated per checkout, and two checkouts on one
machine would overwrite each other's verdicts.

**Use `SHGetKnownFolderPath(FOLDERID_LocalAppData)` through `ctypes` instead of
the environment variable.** The most authoritative route, and immune to a
redirected or unset variable. Rejected for now because it requires `ctypes` and a
hand-written Windows call for a value the platform documents as available in the
environment, and because refusing when the variable is absent is a safe failure
rather than a wrong answer. If a redirected profile ever produces a wrong root,
this is the alternative to revisit — which is why it is recorded here.

**Use a named mutex (`CreateMutexW`) for single-instance detection.** The
idiomatic Windows answer, and it needs no file at all. Rejected because it
requires `ctypes` and Win32 error-code handling, while `msvcrt.locking` is
standard library, was measured to be genuinely cross-process, and leaves an
artefact an operator can see. The named mutex also has no natural place to carry
instance metadata.

**Treat the presence of `instance.lock` as evidence of a running instance, and
delete it when stale.** The most common implementation of this pattern, and the
reason the pattern has a bad reputation. Rejected outright: it is wrong after
every crash, and the "delete when stale" repair is a race — two processes can both
decide a file is stale and both proceed.

**Have `doctor` acquire the real lock for its duration.** Simpler: one code path
instead of two. Rejected because it makes a read-only diagnostic unusable at
exactly the moment somebody needs it, which is while GLOBIN is running.

**Write state with `Path.write_text` and accept the risk.** What Phase 021 does
today. Rejected because it is the specific failure this record exists to remove,
and because the fix costs one helper.

**Rely on `atexit` for cleanup rather than `try`/`finally`.** Less code, and it
appears to cover more exits. Rejected because it covers *fewer*: it does not run
on a hard kill, and presenting it as crash protection would be a claim the
mechanism cannot support.

## Risks and Trade-offs

**The characteristic failure mode is the runtime tree becoming a dumping
ground** — a later phase writing something large, or something secret, into
`state/` because the directory was already there. The observable signal is a
runtime root that grows without bound, or any file under it that a secret scanner
flags. Nothing but the document and review prevents it: no gate can tell a large
file from a small one, and the boundary is a rule rather than a mechanism.

**The second is that the lock's narrowness is forgotten.** The signal is a phase
in the two-hundreds reaching for `InstanceLock` to coordinate workers, for which
it is the wrong shape. This record and `RUNTIME_FILESYSTEM.md` say so; nothing
enforces it.

**The third is that `LOCALAPPDATA` is absent or redirected somewhere
surprising** — a service account, a locked-down profile, a redirected folder on a
network share where `os.replace` is not atomic. The signal is a refusal to start
with the root-resolution message on a host where everything else passes. The
`ctypes` alternative above is the recorded fix, and the network-share case is a
genuine limitation of this design rather than a bug in it.

**The fourth is that the atomic writer is bypassed.** Nothing forces a future
caller to use it, and `Path.write_text` remains one import away. The signal is a
truncated document after a crash — which is precisely the symptom that motivated
this, so it would be recognised, but only after it happened.

Confidence is high on the locking and atomic-publication semantics: both were
measured on the target host rather than assumed, and both are standard-library
mechanisms read from primary documentation
([`../research/phase_022_sources.md`](../research/phase_022_sources.md)).
Confidence is moderate on the four-directory shape, which has one consumer today
and is being designed for consumers two bands away.

## References

- [ADR-0014](0014-layered-ports-and-adapters-and-inward-dependencies.md) — the layer contract, and why a `Path` stays out of the domain
- [ADR-0015](0015-single-composition-root-and-no-import-time-side-effects.md) — where the wiring lives
- [ADR-0048](0048-a-secret-lives-outside-the-tree-and-is-redacted-before-a-record-exists.md) — why nothing here may carry a secret
- [ADR-0050](0050-the-runtime-is-a-declared-contract-and-venv-is-its-only-environment.md) — the constraint on what tooling may touch, and why the application needed its own answer
- [ADR-0056](0056-phase-021-widens-to-deliver-the-application-bootstrap.md) — the bootstrap this extends, and the reservations it left
- [ADR-0057](0057-phase-022-widens-to-deliver-the-runtime-filesystem-and-lifecycle.md) — the amendment that put this work in this phase, and the eight phases it displaces
- [`../CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md) — the Phase 027 boundary this respects
- [`../engineering/RUNTIME_FILESYSTEM.md`](../engineering/RUNTIME_FILESYSTEM.md) — the operator-facing contract
- [`../engineering/BOOTSTRAP.md`](../engineering/BOOTSTRAP.md) — the startup pipeline these checks join
- [`../research/phase_022_sources.md`](../research/phase_022_sources.md) — `os.replace`, `os.fsync`, `msvcrt.locking`, `signal`, `atexit` and the Known Folders documentation

## Supersedes

None.

## Superseded By

None.
