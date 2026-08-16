# ADR-0063 — A measurement that was not taken is never zero, and a support bundle is allowlist-first, self-validating and atomically published

## Status

Accepted — Phase 024.

**Date:** 2026-08-16

## Context

Phase 021 built a bootstrap, Phase 022 gave the process somewhere to keep state,
Phase 023 gave it a voice. None of them let a running GLOBIN answer *how am I doing
now*, and none gave an operator a supported way to hand over evidence when
something went wrong. Hand-picking files out of a runtime tree is how a credential
leaves a machine.

Three constraints shaped what could be built.

**The CI `quality` job has no `psutil`.** It installs the development toolchain
with plain `pip` and never builds `.venv`, so a module-level `import psutil` would
make the smoke test and mypy fail there while passing on every developer's machine.

**Redaction matches field names.**
[`../engineering/RUNTIME_DIAGNOSTICS.md`](../engineering/RUNTIME_DIAGNOSTICS.md)
already states that a credential inside free text survives Phase 023's redactor.

**A support bundle is built to leave the machine.** Everything GLOBIN had written
before this was for GLOBIN or for CI.

## Decision

### A measurement that was not taken is never zero

`Availability` carries four words — `measured`, `unavailable`, `unsupported`,
`denied` — and every numeric field in a health snapshot is a `Reading` rather than
an `int`. The type refuses at construction both a measured reading with no value
and an unmeasured one carrying a value, because each is a state that makes every
downstream consumer wrong and each is cheap to create by accident.

The alternative is what makes this worth a record. A dashboard showing 0% memory
used because nothing could read it looks exactly like a dashboard showing a healthy
process, and the second is a conclusion nobody drew. ADR-0045 made absence a
recorded state for a *device*; this applies the same rule to a *measurement*, and
`psutil` being absent is the case that proves it.

**No instantaneous CPU percentage is reported.** psutil documents that the first
`cpu_percent` call on a process returns a meaningless `0.0`, because a percentage
is a ratio over an interval. A command that measures once and exits has no
interval, so cumulative CPU times are reported and the percentage is `unavailable`.

### psutil is reached through one factory, and absence is not an error

`system_process_probe()` returns a psutil-backed probe or one recording
`UNAVAILABLE`, and no other module in the package names psutil —
`tests/architecture/test_probe_discipline.py` enforces that on the real import
graph. This is not defensiveness for its own sake: it is what makes the CI job
honest rather than guarded, and it is the same injection idiom `system_hooks()`
already uses.

### An unmeasurability that was predicted does not make a system amber

`aggregate_state` forgives an `unknown` on a check whose registry entry carries
`tolerates_unknown`. Without it the CI host reports `degraded` on every run
forever, and a signal that is always amber is a signal nobody reads.

Forgiving it in the verdict does not hide it: every unmeasured check keeps its
reason code, `unmeasurable()` counts them regardless of the state, and the human
rendering prints the list.

### A check that raises does not take the snapshot with it

The exception becomes an `unknown` result carrying `HEALTH_CHECK_RAISED` and is
reported through the Phase 023 sinks. Nothing is discarded, so
[`../engineering/ENGINEERING_CONTRACT.md`](../engineering/ENGINEERING_CONTRACT.md)
invariant 23 is satisfied rather than dodged. Only the exception's **type** is
recorded — its message and traceback are not, because a third-party exception's
text is exactly where a credential ends up and redaction matches field names.

`Exception` and not `BaseException`: a `KeyboardInterrupt` means somebody asked the
process to stop, and swallowing one to finish a diagnostic would be the health
surface refusing to let go.

### A bundle is allowlist-first, and there is no directory walk

`ArtifactKind` enumerates what may be included and `bundle_candidates` is the table
naming every file. A collector that zipped the runtime tree and excluded known-bad
names would be one unanticipated file away from shipping it.

The cost is that a genuinely useful new file does not appear until somebody adds a
kind for it, which is the correct direction to fail in.

### The manifest describes everything except itself

A manifest carrying its own digest would describe a file that changes the moment
the description is written, which has no fixed point. It is built over the
collected members and the report, written last, and the validator is told its name
so it can check the archive holds exactly the described set plus that one file.

An earlier draft of this built the manifest before the report existed and shipped a
bundle whose index listed one of three members. The archive was internally
consistent and the index was wrong, which is the failure a self-validating format
exists to make impossible.

### Validation reopens the finished file, and publication is atomic

A manifest generated from the same in-memory objects that produced the archive
establishes only that the code agrees with itself. The validator reopens it through
`zipfile`, recomputes every digest from the stored bytes, and compares the member
set **in both directions** — a manifest missing a member that is present is as
wrong as one naming a member that is not, and the first is the shape a leak has.

The archive is built under a `.partial` name **in the destination's own directory**
— `os.replace` is atomic only within one filesystem — validated, hashed, and only
then moved. It reuses
`globin.adapters.runtime_state.FileOperations` so the same injected seams work.

### Determinism is claimed narrowly

Two runs at different times produce different archives, and the documentation says
so. What is guaranteed for the same logical inputs is the member list and its
order, the member names, the canonical JSON bytes, the ZIP metadata, the
compression method and level, and normalised member timestamps. Real modification
times are discarded: they vary with when a file was touched rather than with its
content, and on this host they would record when an operator was at their machine.

### `zipfile` and `tracemalloc` join the I/O-capable list

`zipfile` opens a path and writes to it — I/O spelled as a container format, which
is how it would have got past a reviewer looking for `open`. `tracemalloc` is the
one entry that reaches *inward*: starting it mutates interpreter-global state that
changes the cost of every allocation in the process, and an inner layer able to
switch a profiler on is exactly the hidden global state invariant 5 forbids.

## Consequences

`docs/engineering/RUNTIME_HEALTH.md` and `docs/engineering/SUPPORT_BUNDLE.md`
become documents that must be kept true.

GLOBIN now produces an artefact intended to be sent to somebody. That makes
redaction a shipping property rather than a hygiene one, and it makes the list of
things never collected — rather than redacted — part of the contract.

A thirteen-setting `diagnostics` section joins the configuration register, and
`known_keys()` unions two sections for the first time. `_flag` is the register's
first boolean binder and is stricter than Python: `"false"` is `False`, and nothing
but `true`/`false` is accepted, because `bool("false")` being true would silently
turn the profiler on.

The CLI gains a `diagnostics` verb with three subcommands. `doctor` and `bootstrap`
are untouched.

## Alternatives Considered

**Report `0` for an unreadable counter.** Simplest, and it is what most health
surfaces do. Rejected for the reason the whole first section gives.

**Make `psutil` an optional dependency resolved at import.** Rejected: the
repository has no optional runtime dependencies, and the gates would see two
different worlds. The factory achieves the same outcome with one code path and a
recorded state.

**Treat every `unknown` as `degraded`.** The brief's rule, and consistent with
`exit_code_for` making unmeasured outrank failed. Put to the owner as an explicit
choice against the tolerant rule; the owner chose tolerant, because a permanently
amber CI host teaches people to ignore amber.

**Have the manifest describe itself with a placeholder digest.** Rejected: a
placeholder that never verifies is worse than an absence that is explained.

**Add a sixth `RuntimeArea` for bundles.** Rejected. A bundle is a bounded,
reproducible artefact an operator may delete, which is what `cache` is for, and
ADR-0059 already warned that the runtime tree's failure mode is becoming a dumping
ground.

**Write thread stacks into the default snapshot.** Rejected: a stack names
functions, files and line numbers, and a thread parked inside a credential read
would say so. Phase 023's `faulthandler` already owns native tracebacks.

## Risks and Trade-offs

**The characteristic failure mode is the allowlist rotting into a denylist.** The
observable signal is a `glob` or an `iterdir` appearing in the collector, at which
point the guarantee becomes "we excluded what we thought of".

**The second is redaction being believed to cover more than it does.** It matches
field names; `faults.txt` is native traceback text nothing parses. The signal is a
phase putting a secret into a message on the grounds that the bundle is redacted.

**The third is `tolerates_unknown` becoming a way to quieten a noisy check.** The
signal is a registry entry whose tolerance nobody can explain in a sentence.

**The fourth is that the health model ossifies around one consumer.** It has
exactly one today — a CLI command — and is being designed for consumers in the
two-hundreds. The signal is Phase 276 or 280 finding the summaries the wrong shape
and building a parallel one rather than changing this.

Confidence is high on the archive, path-safety and publication semantics, which are
standard and were read from primary documentation
([`../research/phase_024_sources.md`](../research/phase_024_sources.md)). It is
moderate on the check registry, which is eighteen checks chosen from what this
process can currently observe.

## References

- [ADR-0019](0019-single-quality-entrypoint.md) — why the parser is hand-written
- [ADR-0026](0026-correlation-is-bound-explicitly-not-ambiently.md) — correlation is passed, never ambient
- [ADR-0045](0045-a-platform-capability-is-a-recorded-state-never-a-pass.md) — the rule this extends from devices to measurements
- [ADR-0056](0056-phase-021-widens-to-deliver-the-application-bootstrap.md) — the exit-code contract this extends by one
- [ADR-0059](0059-the-mutable-runtime-tree-is-user-local-and-one-coordinator-is-proved-by-a-lock.md) — the atomic publication and lock semantics reused here
- [ADR-0060](0060-gpu-capability-is-detected-and-the-runtime-explains-itself.md) — the redactor and the fault file a bundle reads
- [ADR-0061](0061-phase-024-widens-to-deliver-runtime-health-and-support-bundles.md) — the amendment this half sits inside
- [`../engineering/RUNTIME_HEALTH.md`](../engineering/RUNTIME_HEALTH.md) — the health model in prose
- [`../engineering/SUPPORT_BUNDLE.md`](../engineering/SUPPORT_BUNDLE.md) — the bundle in prose

## Supersedes

None.

## Superseded By

None.
