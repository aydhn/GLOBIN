# ADR-0060 — GPU capability is detected as a recorded state, the runtime is given diagnostics, and this is the seventh amendment

## Status

Accepted — Phase 023.

**Date:** 2026-08-16

## Context

`ROADMAP.md` gives Phase 023 one job: *NVIDIA Driver and CUDA Capability
Detection* — "detect GPU presence, driver version, compute capability and CUDA
availability without assuming any of them". The band it sits in says the same
thing again: "honest verification of GPU capability rather than assumption".

The phase brief handed to this phase asked for something else entirely:
structured runtime logging, correlation context, redaction, log rotation,
unhandled-exception and fault capture, and diagnostic evidence.

**Most of that brief was already delivered, and the brief did not know it.** Phase
006 — *Structured Logging Foundation*, status `Complete` — built a self-redacting
`LogEvent`, a one-method `LogSink` port, an immutable `Logger` whose `bind`
returns a new logger, and a JSON-Lines sink. Phase 007 added the severity
threshold and the typed configuration the brief attributed to "Phase 19". Phase
015 established the secret-handling baseline the brief attributed to "Phase 20".
The brief's numbering does not match this repository at any point: it named
Phase 19 for configuration (actually 007), Phase 20 for a secret store (actually
015 for the rules, and **028**, unstarted, for the store), and Phase 282 owns log
rotation and retention by name.

The brief also asked for two things this repository had already refused **in
writing**. [ADR-0026](0026-correlation-is-bound-explicitly-not-ambiently.md)
records why correlation is bound explicitly rather than through
`contextvars`; `adapters/observability.py` records why the standard library's
`logging` is not used. Both refusals rest on `ENGINEERING_CONTRACT.md` invariant
5, and invariant 5 is enforced by a test rather than trusted.

There is nonetheless a real gap, and it should be stated rather than implied.
**Nothing in the product logged.** `build_logger` had no production caller; the
CLI printed with `print`. Phase 021 declared a `logs` path that
[ADR-0056](0056-phase-021-widens-to-deliver-the-application-bootstrap.md) is
explicit nothing creates, and Phase 022 then moved mutable state to a user-local
tree with four areas and no logs among them — so the reservation pointed at a
directory in the wrong root. A process that had been told it may start could
explain nothing about what it then did, and a process that died explained nothing
at all.

The conflict was surfaced to the owner as a choice between four courses — deliver
the roadmap's Phase 023 and record the brief as a proposal; deliver Phase 023 plus
only the unowned seam; deliver both in full; or deliver the brief alone and
retitle the phase — and the owner chose to deliver both.

## Decision

**Phase 023 delivers both halves**, and this is the **seventh roadmap scope
amendment**.

[ADR-0021](0021-phase-005-widens-to-include-the-test-foundation.md) set a
four-part test for whether an amendment is covered by precedent.
[ADR-0057](0057-phase-022-widens-to-deliver-the-runtime-filesystem-and-lifecycle.md)
closed by removing the option of citing it or the series, and named the
observable signal of the failure it feared: an amendment "that does not restate
ADR-0021's four criteria and score itself against them". The test is therefore
restated in full and scored honestly rather than cited:

| ADR-0021's test | This amendment |
|---|---|
| Nothing displaced | **Fails.** Rotation and retention are Phase 282's by name. Parts of 026, 027 and 030 arrive here. |
| Nothing deferred | **Holds.** Phase 023's declared scope is delivered in full, and no other phase's title changes. |
| No phase owns the work | **Fails, and worse than any predecessor.** Phase 006 delivered the logging foundation and is marked `Complete`. This is the first amendment to overlap a phase that has *already shipped* rather than one that has not started. |
| The two halves need each other | **Fails.** GPU detection and runtime diagnostics are wholly independent. Either could ship alone and no gate refused until both existed. |

**One of four.** The fourth amendment scored two, the fifth scored two, the sixth
scored one, and this scores one — but the criterion it fails is a worse one to
fail. Every previous amendment displaced work from phases that had not started.
This one overlaps Phase 006, which is complete, which means the honest description
is not only *displacement* but *duplication of delivered work*. The mitigation is
that the overlap was found and refused rather than built: the schema was not
replaced, `contextvars` was not adopted, and `logging` did not enter GLOBIN's call
sites. What shipped is the part Phase 006 could not have built, because in Phase
006 there was no application to instrument.

It is taken on the owner's explicit decision, made with the conflict and the four
alternatives in front of them.

### What the amendment refuses to build

The second half is bounded by what it declines, and the boundary is the reason the
owning phases still have work.

- **No audit trail (281) and no metrics (280).** The lifecycle events are the
  names a start-up and a shutdown produce. They are not an append-only ledger and
  nothing counts anything.
- **No retention policy, compression or archival (282).** A size bound and a
  backup count arrive here because an appending file in the runtime tree is
  otherwise unbounded, and ADR-0059 named that as its own characteristic failure.
  What retention *means* — how long an operator must keep what, and why — is not
  decided.
- **No configuration file layout (026) or environment resolution (027).** Two
  typed settings are added through the route `CONFIGURATION_POLICY.md` documents.
  **No new `os.getenv` call is added anywhere**, holding the line ADR-0057 drew.
- **No secret store (028).** Nothing here holds, reads or writes a credential, and
  the name `SecretRef` is still forbidden until that phase.
- **No event loop.** An asyncio handler is *built* and never installed, because
  GLOBIN starts no loop until Phases 033-048 and reaching for a running one would
  mean creating it early to have something to attach to.
- **No benchmark (024).** The GPU half detects and records. Which workloads
  benefit is the next phase's question, and nothing here times anything.

### The decisions the first half fixes

**A GPU capability is a recorded state, never a pass.**
[ADR-0045](0045-a-platform-capability-is-a-recorded-state-never-a-pass.md)
settled this for platform controls and hardware is the same question with a
different subject. Four states — `PRESENT`, `ABSENT`, `UNMEASURABLE`, `ERROR` —
and the last always fails while the second never does. A gate that went red on a
machine with no NVIDIA card would be reporting the hardware rather than the
repository, and would be permanently red on `windows-latest`, where continuous
integration runs.

**`ABSENT` and `UNMEASURABLE` are different claims.** *We asked and there is none*
and *there was nothing to ask* are not the same fact, and a later phase reading
the manifest needs to tell them apart.

**The contract declares an interface, not a baseline.** No driver version, no
compute capability and no device name is committed. A driver updates on its own
schedule; a pinned value would go red on a day nobody chose and then be bumped
without being read. The observed values live in the regenerated manifest.

**Only `nvidia-smi`'s own documented vocabulary is read, and the deprecated parts
of it are named and refused.** Four traps were measured on the target host rather
than assumed, and each is recorded in `docs/research/phase_023_sources.md`:
`cuda_version` is not a queryable field and asking for it breaks the *entire*
query; `DRIVER version` and `CUDA version` are answered by the driver with the
word *Deprecated* and a pointer elsewhere; and the banner spelling has already
changed once. A detector reading any of them would publish a sentence where a
version belongs, and nothing downstream could tell it from a measurement. Hence
the `[[forbidden_field]]` table, checked against the interface table in the same
file, plus a shape check on every recorded value.

**A CUDA runtime and a CUDA toolkit are asked separately and neither is inferred
from the other.** The target host has the first without the second, which is the
proof that the inference would be wrong. The distinction is *a prebuilt CUDA wheel
would run here* versus *CUDA source could be built here*, and collapsing it into
one boolean would destroy exactly what Phase 024 needs.

### The decisions the second half fixes

**The existing logging architecture is extended, not replaced.** The envelope,
the redaction mechanism, the severity policy and explicit correlation are
unchanged. The brief's alternative schema was not adopted; extra detail rides in
`fields`, where redaction still applies.

**The bridge is the addition Phase 006 designed for.**
`adapters/observability.py` wrote that when a dependency first emits
standard-library records, "a second `LogSink` implementation bridges them; the
port is what makes that an addition rather than a rewrite". Phase 021 adopted
`numpy` and `pandas`, so that dependency now exists. Warnings arrive through the
same handler, so there is one thing to install and one to remove.
`tests/architecture/test_logging_discipline.py` fails if GLOBIN's own call sites
start using `logging`.

**`logs` is a fifth runtime area, and it is bounded because it is the only one
that is appended to.** Every other area holds small documents published whole and
atomically. `RotationPolicy` is a validated value type: a policy that could not be
honoured cannot be constructed, and `ceiling_bytes()` states the worst case as a
number rather than leaving a reviewer to multiply.

**The file sink flushes every record and the stream sink does not.** The file
exists so that a process which dies badly leaves an explanation behind, and an
explanation still in a buffer when the interpreter is killed is not one.

**Hooks replace rather than chain, and are injected rather than reached for.** The
default `sys.excepthook` prints prose to standard error; calling it as well would
double every report and put prose in the stream `--json` promises is clean. The
registry is injected for the reason `PlatformShutdownSignals` takes its
`registrar`: a test that installed a real hook and failed before restoring it
would break every later test, and the suite's process-state guard does not watch
hooks.

**An orderly exit is recorded, not mourned.** `SystemExit` and `KeyboardInterrupt`
are `INFO`. `CRITICAL` means GLOBIN cannot do its job, and an operator who sees it
on every Ctrl-C stops reading it.

**One place swallows an exception, and it is not silent.** A fault reporter whose
own sink fails writes to `stderr`. A hook runs when the process is already
failing, and an exception raised inside `sys.excepthook` is printed and discarded
by the interpreter — so it can only replace the report with a worse one. Invariant
23 forbids swallowing *silently*.

**`faulthandler` writes plain text to its own file, and no signal is registered.**
`faulthandler.register` does not exist on Windows, measured rather than assumed.
The output is not JSON because it is written by C with no encoder involved, which
is the entire reason it works when the interpreter cannot run Python.

## Consequences

Phase 282 is now smaller than its title suggests, and Phases 026, 027 and 030
smaller again. `ROADMAP.md` says so for 282 in the amendment entry; whoever
reaches the others must read this record to learn what already exists.

**Phase 006 is now partly re-described by a later phase, which is new.** Every
previous amendment displaced work forwards into phases that had not started. A
reader of `LOGGING_POLICY.md` will find the record shape and the redaction list
there and the runtime behaviour in `RUNTIME_DIAGNOSTICS.md`, and the split between
those two documents is the cost of this amendment paid in documentation.

`docs/engineering/GPU_CAPABILITY.md` and
`docs/engineering/RUNTIME_DIAGNOSTICS.md` become documents that must be kept true.

`faulthandler` joins `[io] capable_modules`, tightening the layer contract rather
than loosening it.

GLOBIN now writes a **growing** file for the first time. Everything before this
was a small document replaced atomically. The bound is enforced by a value type
and asserted by a test, but the property "nothing GLOBIN writes grows" is gone,
and it was worth something.

The programme's fixity has now been amended seven times in twenty-three phases.
ADR-0016's warning — that a third amendment before Phase 016 would signal the
roadmap being treated as a backlog — has been passed three times over. This record
does not argue that the signal is wrong.

## Alternatives Considered

**Deliver the roadmap's Phase 023 alone, and record the brief as a proposal
against the phases that own it.** The course with no amendment, and the one the
source-of-truth order points at. It was the recommendation the conflict was
surfaced with. Declined by the owner. It would have left the application unable to
explain itself until Phase 282 at the earliest, and left Phase 021's `logs`
reservation pointing at the wrong root indefinitely.

**Deliver Phase 023 plus only the unowned seam** — wiring the existing logger,
adding a file sink, fixing the stale reservation, adding the fault hooks — and
leave rotation with Phase 282. A materially smaller amendment, and the one that
would have scored best of the four. Declined by the owner in favour of the full
brief. Its cost was that an appending file with no bound is precisely the failure
ADR-0059 warned about, so the seam could not honestly be closed without *some*
bound, and a bound is most of what Phase 282's rotation is.

**Deliver the brief alone, retitling Phase 023.** Rejected because it displaces
*and* defers: GPU detection would have had to move, and Phase 024's harness
depends on 023 having measured the host it is about to benchmark.

**Adopt `contextvars` for correlation, as the brief specified.** Rejected because
ADR-0026 refused it on invariant 5, and reversing an accepted ADR to satisfy a
brief that misidentified which phase wrote it is the weakest possible reason to
reverse one. The owner was asked directly and chose to honour both ADRs.

**Route GLOBIN's own call sites through `logging`, as the brief specified.**
Rejected for the same reason, and because the bridge satisfies the actual
requirement — third-party records and Python warnings reaching GLOBIN's sinks —
without module-level handler state.

**Replace the record envelope with the brief's schema.** Rejected because
`ENVELOPE_KEYS` is contract-tested against `LOGGING_POLICY.md`, every field the
brief wanted fits under `fields`, and a second record shape would have to be kept
in step with the first forever.

**Put the log file in `state/`.** Rejected because `state/` holds small documents
published atomically, and putting the one growing file among them is exactly the
failure ADR-0059 predicted about adding a directory. A separate area is what lets
the bound apply to the growing thing and not to the small ones.

## Risks and Trade-offs

**The characteristic failure mode is that a later phase reads this as permission
to re-deliver completed work.** Six amendments displaced work forwards; this one
overlaps a phase marked `Complete`. The observable signal is a phase brief
proposing to rebuild something whose ADR already exists, and an ADR that accepts
it without saying which completed phase it overlaps.

**The second is that the logs area becomes the dumping ground ADR-0059 warned
about**, now with a directory whose stated purpose is *files that grow*. The bound
is enforced, but only for the sink GLOBIN ships; nothing stops a later phase
opening its own handle there. The signal is a second writer in `logs/` that does
not go through `RotatingFileLogSink`.

**The third is that redaction is believed to cover more than it does.** Redaction
is by field *name*. A credential inside an exception message reaches
`exception_message` and is written, and this phase does **not** fix that —
`RUNTIME_DIAGNOSTICS.md` says so in as many words. Nothing can fix it until Phase
028 gives GLOBIN a set of secret values to scan for. The signal that this was
forgotten is a later phase citing "redaction is in place" as the reason it may
pass a credential to a diagnostic.

**The fourth is that the GPU contract ossifies around one vendor's tool.**
Everything here reads `nvidia-smi`. A host with an AMD or Intel device is
correctly reported as having no NVIDIA device, which is true and unhelpful. The
signal is a phase needing a non-NVIDIA answer and finding the contract has no
shape for one.

**The fifth is that `DELIVERED_PHASE` in the GPU gate drifts.** It is 23 rather
than 22 because a capability may not be owned by the phase recording it — the
first version was 22 and a unit test caught the mismatch between the number and
the sentence explaining it. The signal is a capability entry naming a phase that
has since shipped.

Confidence is high on the GPU half, which is measurement against a documented
interface with every trap recorded. It is high on the logging half's mechanics,
which extend a design that already existed and is contract-tested. It is
deliberately not stated as high anywhere in the amendment reasoning, because the
amendment reasoning is the part that scored one of four — and, on the criterion it
fails worst, scored worse than any amendment before it.

## References

- [ADR-0014](0014-layered-ports-and-adapters-and-inward-dependencies.md) — the layer contract this does not change
- [ADR-0015](0015-single-composition-root-and-no-import-time-side-effects.md) — why nothing installs a hook at import
- [ADR-0016](0016-phase-004-absorbs-the-quality-gate-scope.md) — what a second amendment costs, and the warning about a third
- [ADR-0021](0021-phase-005-widens-to-include-the-test-foundation.md) — the four-part amendment test, restated and scored above rather than cited
- [ADR-0025](0025-structured-logging-is-a-redacted-domain-event.md) — the record this phase extends rather than replaces
- [ADR-0026](0026-correlation-is-bound-explicitly-not-ambiently.md) — the refusal the brief asked to reverse, and which stands
- [ADR-0029](0029-a-severity-threshold-is-a-decorating-sink.md) — why the fan-out's elements hold their own thresholds
- [ADR-0032](0032-verification-tooling-may-be-added-outside-phase-scope.md) — the six conditions the GPU gate is held to
- [ADR-0045](0045-a-platform-capability-is-a-recorded-state-never-a-pass.md) — the state-not-a-pass rule this applies to hardware
- [ADR-0048](0048-a-secret-lives-outside-the-tree-and-is-redacted-before-a-record-exists.md) — redaction before a record exists, and its limits
- [ADR-0052](0052-wheel-availability-is-a-recorded-survey-whose-verdict-is-recomputed.md) — the owned-gap rule reused here
- [ADR-0056](0056-phase-021-widens-to-deliver-the-application-bootstrap.md) — the fifth amendment, and the `logs` reservation this resolves
- [ADR-0057](0057-phase-022-widens-to-deliver-the-runtime-filesystem-and-lifecycle.md) — the sixth amendment, whose precedent this record does not claim
- [ADR-0059](0059-the-mutable-runtime-tree-is-user-local-and-one-coordinator-is-proved-by-a-lock.md) — the runtime tree this adds a fifth area to
- [`../engineering/GPU_CAPABILITY.md`](../engineering/GPU_CAPABILITY.md) — the first half's document
- [`../engineering/RUNTIME_DIAGNOSTICS.md`](../engineering/RUNTIME_DIAGNOSTICS.md) — the second half's document
- [`../research/phase_023_sources.md`](../research/phase_023_sources.md) — every measurement behind both halves

## Supersedes

None.

## Superseded By

None.
