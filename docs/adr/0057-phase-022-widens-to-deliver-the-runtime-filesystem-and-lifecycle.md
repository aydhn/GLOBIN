# ADR-0057 — Phase 022 widens to deliver the runtime filesystem and lifecycle, and this is the sixth amendment, and the weakest

## Status

Accepted — Phase 022.

**Date:** 2026-08-16

## Context

`ROADMAP.md` gives Phase 022 one job: *Scientific Stack Installation and
Verification* — "install and verify the numerical and dataframe stack,
confirming correctness rather than assuming it". That ownership is not stated
once. It is in the phase row, in the roadmap's own prose ("Phase 022 installs and
verifies the scientific stack"), and in
[`../engineering/wheel-survey.toml`](../engineering/wheel-survey.toml), which
files `numpy` and `pandas` under `phase = 22` and names them the numerical and
dataframe halves of the Phase 022 stack.

The phase brief handed to this phase asked for something else entirely: a
deterministic runtime filesystem layout, atomic state persistence, single-instance
locking, graceful shutdown and crash-safe runtime evidence. Every one of those
subjects is owned by a planned phase **by name** — 026 (configuration file layout),
030 (bootstrap health check suite), 257 (orchestrator architecture), 262
(subsystem lifecycle management), 266 (persistent orchestration state), 267 (crash
recovery and resumption), 268 (graceful shutdown and draining) and 270 (Windows
service and continuity behaviour).

The conflict was surfaced to the owner as a choice between three courses —
deliver the roadmap's Phase 022 and record the rest as a proposal; deliver the
brief and retitle the phase; or deliver both — and the owner chose both.

There is also a real gap that gave the second half its pressure, and it should be
stated rather than implied. Phase 021 built a bootstrap that assembles a
`RuntimeContext` and then hands it to nothing. `RuntimePaths` declares `state`,
`cache` and `logs` roots which
[ADR-0056](0056-phase-021-widens-to-deliver-the-application-bootstrap.md) is
explicit are *reservations* that nothing creates. So a process that has been told
it may start still has nowhere to put mutable state, no way to know it is the only
one running, and no defined way to stop. The bootstrap's own evidence writer uses
`Path.write_text`, which is not atomic: a process killed mid-write leaves a
truncated manifest that the reader then refuses, turning a crash into a second
failure.

None of that makes the amendment *covered*. It explains why the work is
worth doing, not why it belongs here.

## Decision

**Phase 022 delivers both halves**, and this is the **sixth roadmap scope
amendment**.

[ADR-0021](0021-phase-005-widens-to-include-the-test-foundation.md) set a
four-part test for whether an amendment is covered by precedent, and
[ADR-0056](0056-phase-021-widens-to-deliver-the-application-bootstrap.md) closed
by naming its own characteristic failure: "an amendment citing *as in Phase 021*
without restating the test". The test is therefore restated in full and scored
honestly rather than cited:

| ADR-0021's test | This amendment |
|---|---|
| Nothing displaced | **Fails.** Parts of 026, 030, 257, 262, 266, 267, 268 and 270 arrive here. |
| Nothing deferred | **Holds.** Phase 022's declared scope is delivered in full, and no other phase's title changes. |
| No phase owns the work | **Fails.** Eight planned phases own parts of it by name. |
| The two halves need each other | **Fails.** The scientific stack and the runtime filesystem are independent. Either could ship without the other, and no gate refused until both existed. |

**One of four.** The fourth amendment scored two, the fifth scored two, and
[ADR-0051](0051-phase-017-absorbs-interpreter-pinning-and-the-environment-lifecycle.md)
said a fifth has a higher bar than a fourth did, not a lower one. By that
standard this is the weakest amendment in the programme so far, and the record
says so plainly. It is taken on the owner's explicit decision, made with the
conflict and the three alternatives in front of them.

The fourth criterion is the one worth dwelling on, because it is the one the
fifth amendment cleared and this one cannot. Phase 021 could point at a gate that
*refused* until both its halves existed. Nothing here refuses. The two halves of
Phase 022 share a phase number and nothing else, and a reader who wants to know
why they shipped together will find the answer in this paragraph rather than in a
technical necessity.

### What the amendment refuses to build

The second half is bounded by what it declines, and the boundary is the reason
the owning phases still have work to do.

- **No orchestrator (257), supervisor or watchdog (263).** The lock introduced
  here guards one top-level coordinator against being started twice. It is not a
  general mutex for future workers or child processes.
- **No subsystem lifecycle (262).** There are no subsystems to start in
  dependency order.
- **No draining (268).** Shutdown releases this process's own resources. Nothing
  is in flight, because nothing reaches an exchange.
- **No crash recovery (267).** A previous run that did not close cleanly is
  reported as a diagnostic. Nothing is resumed, repaired or reconciled — and a
  trading reconciliation, which is Phase 095, is emphatically not this.
- **No configuration file layout or profiles (026), and no environment-variable
  resolution (027).** A runtime-root override is added as a typed field with a
  default, through the route `docs/CONFIGURATION_POLICY.md` documents. **No new
  `os.getenv` call is added anywhere**, because reading one would settle Phase
  027's question by accident — the same trap that document already names about
  creating `config/` early.
- **No secret store (028).** Nothing here holds, reads or writes a credential.

### The decisions the second half fixes

**There are two roots, and the second is new.** `.globin/` inside the repository
stays what it already is: evidence written by verification tools *about this
repository*. Mutable application state moves to a user-local root under the
Windows Local Application Data area. That distinguishes two things Phase 021
conflated; it does not reverse Phase 021, whose `state`, `cache` and `logs`
entries were reservations that nothing had created.

**A declared path is still a string, and a resolved path still never reaches the
domain.** `docs/architecture/dependency-rules.toml` lists `pathlib` among the
I/O-capable modules and the domain may import none of them, so the
`pathlib.Path`-typed layout the brief asked for is built in the adapters layer.
The domain declares relative segments and publishes `RecordedPath`. This is
ADR-0056's rule applied unchanged rather than a new one.

**The presence of a lock file is never evidence that an instance is running.**
A crashed process leaves its lock file behind. Ownership is decided by the result
of a non-blocking `msvcrt.locking` acquisition and by nothing else. A stale file
must not block a start-up, and no stale file is deleted on the strength of a
guess about who owns it.

**A small state document is published atomically or not at all.** Write to a
unique temporary file in the destination's own directory, flush, `os.fsync` the
descriptor, close, then `os.replace`. A reader must never observe a truncated
document, and a failed write must leave the previous one intact.

**Cleanup is `try`/`finally`; `atexit` is a net.** `atexit` runs on normal
interpreter termination and not on a kill or a power loss, so it is registered as
a best-effort fallback and is never the mechanism a guarantee rests on. Signal
handlers set an intent flag and return; the work happens on the ordinary control
flow.

**Signals are registered only where the platform has them.** `SIGINT` and
`SIGTERM` always; `SIGBREAK` only when the running Python exposes it.

### The decisions the first half fixes

**The stack's verdict is recomputed from measurement.** A gate that concluded
"installed" because `import numpy` did not raise would be assuming exactly what
the roadmap asks it to confirm. `python -m tools.quality stack` compares the
installed version against the lock, the manifest bound and its own declaration,
checks the installed wheel's provenance against the tags the pinned interpreter
accepts, and runs named behaviour probes whose results appear in the evidence.

**Nothing under `src/globin` imports `numpy` or `pandas`, and a test enforces
it.** [`../PRECISION_POLICY.md`](../PRECISION_POLICY.md) rule 1 is a one-way
door — a `float` may never be the last transformation before a venue or a ledger,
and may never decide a refusal — and the same document defers the numeric type
indicators and models use to Phases 113-128. Verifying a stack is not adopting
it, and an architecture tripwire keeps the two apart from this commit onwards.

## Consequences

Eight planned phases are now smaller than their titles suggest, and none of them
says so in `ROADMAP.md`. Whoever reaches 026, 030, 257, 262, 266, 267, 268 or 270
must read this record to learn what already exists. That is the cost of an
amendment that displaces work, and it is paid eight times here rather than once.

The programme's fixity has now been amended six times in twenty-two phases. The
first band's warning — ADR-0016's, that a third amendment before Phase 016 would
signal the roadmap being treated as a backlog — has been passed twice over. This
record does not argue that the signal is wrong.

`docs/engineering/RUNTIME_FILESYSTEM.md` and
`docs/engineering/SCIENTIFIC_STACK.md` become documents that must be kept true.

GLOBIN now writes outside its own repository for the first time. Everything it
writes there is non-secret operational state, the tree is named in
`RUNTIME_FILESYSTEM.md`, and an operator can delete the whole of it without
breaking correctness — but the property "GLOBIN touches nothing outside the
checkout" is gone, and it was worth something.

A sixth amendment scoring one of four sets no precedent that a seventh can lean
on. If anything, it establishes the opposite: the test has now been failed badly
enough that citing the *series* is not available either.

## Alternatives Considered

**Deliver the roadmap's Phase 022 alone, and record the brief's content as a
proposal against the phases that own it.** The course with no amendment at all,
and the one the source-of-truth order points at. Declined by the owner. It was
the recommendation the conflict was surfaced with, and it would have left the
runtime-filesystem work unbuilt until Phase 026 at the earliest and Phase 266 for
most of it.

**Deliver the brief alone, retitling Phase 022.** Rejected because it displaces
*and* defers: the scientific stack would have had to move to another phase, and
the wheel survey's two entries would then point at a phase that had shipped
without adopting them — which
[ADR-0052](0052-wheel-availability-is-a-recorded-survey-whose-verdict-is-recomputed.md)
calls an adoption wearing a survey's clothes.

**Move the whole `.globin/` tree to the user-local root.** Superficially tidier —
one root, one rule. Rejected because the gate evidence under `.globin/` is about
*the repository*, is read by CI, and is regenerated per checkout; putting it in a
user profile would make two checkouts on one machine overwrite each other's
verdicts.

**Keep the mutable tree repository-relative and simply add `run/` and `tmp/`.**
The smallest possible change, and it preserves the "touches nothing outside the
checkout" property. Rejected because it makes the working directory decide where
a running system keeps its state, which is the ambiguity Phase 021 spent its
root search removing, and because two checkouts would then fight over one lock
that neither could see.

**Amend `dependency-rules.toml` to let the domain hold a `pathlib.Path`.** It
would have satisfied the brief's wording directly. Rejected because it inverts the
layer contract for a typing convenience: the domain would then be able to open a
file, and the one-way rule that makes the architecture test meaningful would be
gone.

**Register the lock probe in `doctor` as a real acquisition held for the
command's duration.** Simpler code, one path. Rejected because a diagnostic that
takes the production lock would make `globin doctor` refuse to run beside a
running GLOBIN — a read-only command breaking the thing it was asked to inspect.

## Risks and Trade-offs

**The characteristic failure mode is that this record becomes the precedent it
denies being.** A seventh amendment citing "as in Phase 022" would mean the
series has replaced the test. The observable signal is an amendment entry in
`ROADMAP.md` that does not restate ADR-0021's four criteria and score itself
against them.

**The second is that the user-local root becomes a dumping ground.**
`RUNTIME_FILESYSTEM.md` names what each directory is for and what may never go
there — credentials, market data, ledgers, model artefacts, Parquet datasets. The
signal that it has failed is a later phase writing something large or something
secret into `state/` because the directory was already there. Nothing but the
document and review prevents it; there is no gate that can tell a large file from
a small one.

**The third is that the lock's narrowness is forgotten.** It guards one top-level
coordinator, and Phases 257 onwards need something broader. The signal is a phase
reaching for `InstanceLock` to coordinate workers, which it cannot do correctly —
it is a whole-application mutex, not a resource lock.

**The fourth is that the stack probes ossify around behaviour that is not
actually a contract.** pandas 3.0 deprecates the `mode.copy_on_write` option
because copy-on-write can no longer be disabled; a probe asserting on a
deprecation warning would fail on pandas 4 for a reason unrelated to correctness.
The probes therefore assert on documented numeric semantics and read no
deprecated option. The signal that this was got wrong is a probe failing on an
upgrade while every GLOBIN behaviour still holds.

Confidence is high on the atomic-write and lock semantics, which are standard and
were read from primary documentation
([`../research/phase_022_sources.md`](../research/phase_022_sources.md)). It is
moderate on the runtime-tree shape, which has one consumer today and is being
designed for consumers in the two-hundreds. It is deliberately not stated as high
anywhere in this record's amendment reasoning, because the amendment reasoning is
the part that scored one of four.

## References

- [ADR-0014](0014-layered-ports-and-adapters-and-inward-dependencies.md) — the layer contract this does not change
- [ADR-0016](0016-phase-004-absorbs-the-quality-gate-scope.md) — what a second amendment costs, and the warning about a third
- [ADR-0021](0021-phase-005-widens-to-include-the-test-foundation.md) — the four-part amendment test, restated above
- [ADR-0030](0030-domain-values-are-denominated-wrappers-over-decimal.md) — the denomination rule the stack must not erode
- [ADR-0051](0051-phase-017-absorbs-interpreter-pinning-and-the-environment-lifecycle.md) — the fourth amendment
- [ADR-0052](0052-wheel-availability-is-a-recorded-survey-whose-verdict-is-recomputed.md) — why a survey entry may not name a delivered phase
- [ADR-0055](0055-the-first-runtime-dependencies-are-introduced-and-globin-becomes-installed.md) — the declaration this phase verifies
- [ADR-0056](0056-phase-021-widens-to-deliver-the-application-bootstrap.md) — the fifth amendment, and the bootstrap this extends
- [ADR-0058](0058-the-scientific-stack-is-verified-by-measurement-and-stays-in-the-approximate-regime.md) — the first half's decisions
- [ADR-0059](0059-the-mutable-runtime-tree-is-user-local-and-one-coordinator-is-proved-by-a-lock.md) — the second half's decisions
- [`../PRECISION_POLICY.md`](../PRECISION_POLICY.md) — the one-way door between the exact and approximate regimes
- [`../CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md) — the deferrals to Phases 026 and 027 this respects

## Supersedes

None.

## Superseded By

None.
