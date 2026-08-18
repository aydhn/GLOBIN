# ADR-0080: A check declares whether its answer survives the run

## Status

Accepted — Phase 030.

**Date:** 2026-08-18

## Context

Phase 021 built a registry: eighteen `CheckSpec`s, performed in order, reduced to
one exit code by the earliest refusal. For a command that reports and exits, that is
complete. The instant its answers describe and the instant the process ends are the
same instant, so the question "is this answer still true" never arises.

`ROADMAP.md` row 030 asks for the checks "that must pass before any **long-running**
GLOBIN process starts", and that adjective breaks the identity. A gate that passed
an hour ago is a claim about an hour ago. Some of what the eighteen checks measure
cannot have moved since — an operating system, an interpreter's version, a set of
installed distributions. Some of it moves as a matter of ordinary operation: free
space, a directory's existence, an exclusive lock another process may take.

Nothing in the registry could express the difference.
[`MEMORY.md`](../../MEMORY.md) records that Phase 030 inherits "no suite, no
scheduling and no periodicity", and a schedule is undefinable without first knowing
which answers are worth taking again.

There is a second pressure, recorded rather than discovered. ADR-0076 names the
observable signal that Phase 029 drew its boundary wrongly: "030 finding it must
argue with `checks()` rather than extend it." Any design that required restructuring
the registry would have been that signal firing.

## Decision

**Every registered check declares a `Durability`**, as a field on `CheckSpec`
alongside the exit code it already declares:

- `STABLE` — the answer cannot change while this process runs, so taking it once is
  taking it for the run.
- `PERISHABLE` — it was true when taken and may since have stopped being true.

The line is drawn at **who changes the thing being measured**. A host, an
interpreter, an architecture and a set of installed distributions are changed by an
operator doing something deliberate outside GLOBIN. Free space, a directory and a
lock are changed by ordinary operation, by GLOBIN itself or by anything else on the
machine.

**The default is `PERISHABLE`.** A nineteenth check whose author did not consider
the question costs a re-measurement nobody needed; the opposite default would let an
unconsidered answer be believed for ever.

**Three calls are argued in the registry itself rather than left to a reader.**

- `config.valid` is `STABLE` **because the configuration snapshot is immutable**,
  not because documents are. An operator may edit `config/` mid-run; the process is
  not reading it again. The stability is Phase 007's design showing through.
- `state.previous_run` is `STABLE` because it asks about history, and re-taking it
  later would read *this* run's record — the same name answering a different
  question.
- `bootstrap.ready` is `PERISHABLE` because an aggregate is no stronger than its
  weakest input.

**A `RecheckPolicy` declares the interval, and cannot be constructed at one no
scheduler could honour** — between one second and one hour, `bool` refused. The
default is a minute, deliberately far slower than the watchdog's second: the
watchdog asks whether a component is still moving, this asks whether the host is
still fit, and a disk does not fill in the time it takes to notice it filling.

**The suite is derived from `checks()`, never restated beside it.** Every accessor
on `PreflightSuite` reads the registry, so a check added, renamed or removed there is
added, renamed or removed here in the same edit.

**`bootstrap preflight` runs every check and gates.** That is the third combination
of two switches that already existed — `bootstrap check` stops early and gates,
`doctor` runs everything and reports — because a launcher needs both halves: every
fault in one pass, and a refusal. It introduces no exit code; a preflight refusal is
already describable by the failing check's own.

**Nothing executes a re-take.** GLOBIN has no long-running process. The phase that
starts one honours this policy; until then a scheduler would be a mechanism with no
caller, tested only against itself.

**What this does not cover.** It says nothing about *live* preflight — connectivity,
credentials at a venue, risk ceilings — which is Phase 297's, and which inherits
this classification rather than being displaced by it.

## Consequences

**What this costs.**

- Eighteen registry rows grew a fourth argument. The registry is wider, and a
  nineteenth check now has one more decision to make before it can be added.
- The interval is a constant in `globin.domain.preflight` rather than a setting, so
  an operator cannot tune it. That is deliberate — `CONFIGURATION_POLICY.md` asks a
  proposed setting to have a call site in the phase that adds it, and this has none
  — but it means the first phase that runs a schedule may have to promote it, which
  is a settings-register edit rather than a free change.
- `PreflightOutcome.shelf_life_millis` returns `int | None`. Two shapes is one more
  case at every call site, and the alternative — a sentinel meaning "for ever" —
  was refused because a caller would eventually compare against it numerically.

**What is now prohibited that a contributor might reasonably want.**

- A second list of which checks decay. `SOURCE_OF_TRUTH.md` refuses the duplicate,
  and the derived accessors make it unnecessary.
- A gating class with no non-blocking member. It was designed and dropped:
  `CheckStatus.WARN` already means "performed, not a refusal", and a declared class
  whose only value is `BLOCKING` would be the speculative field
  `CONFIGURATION_POLICY.md` keeps out of the settings register for the same reason.

**What enforcement exists.** `tests/unit/test_preflight.py` asserts that every
registered check declares a durability, that the two classes partition the registry,
that a check built without one is treated as decaying, and that the four calls named
above land where the registry says. The suite's derivation is asserted against
`checks()` directly.

## Alternatives Considered

**Leave the registry alone and put the classification in the suite.** Rejected: a
table listing which checks decay describes checks the registry no longer has the
moment one is renamed, which is exactly the duplication `SOURCE_OF_TRUTH.md` refuses.

**Three or four durability classes** — for instance separating "cannot change" from
"could change but nothing GLOBIN does changes it". Rejected as a distinction with no
consumer: the only thing anybody does with the classification is decide whether to
schedule a re-take, and that is a binary question. A third class would have to name
a behaviour that differs.

**Make the interval a setting.** Rejected today, and the rejection is dated rather
than principled: the register grows in the phase that needs the setting, and no call
site exists. The phase that runs a schedule may reasonably reverse this.

**Build the scheduler now.** Rejected. It would be a loop with no process to run in,
whose only exercise is its own test — and a mechanism tested only against itself is
how a repository acquires code that works until the day something calls it.

**Reuse the watchdog's interval.** Rejected: it answers a different question at a
different rate. Sharing the number would couple a liveness heartbeat to a host
re-measurement, and the first phase that wanted to change one would silently change
the other.

## Risks and Trade-offs

**The characteristic failure mode is a classification that is wrong in the
optimistic direction** — a check marked `STABLE` whose answer does in fact move, so
a long-running process believes something stale for ever. The three calls most
exposed are `dependency.lock` (an operator can install a package into a running
environment), `python.environment` (a `.venv` can be rebuilt underneath a process)
and `config.valid` (whose stability rests on the snapshot being immutable, which is
a property of Phase 007's design rather than of the filesystem).

**The observable signal is a stale-verdict incident**: a process that kept running
on a claim that had stopped being true, where the check that made the claim is
marked `STABLE`. The remedy is one word in one registry row, which is why the
classification lives there.

**The second risk is the unrun schedule.** A policy nobody executes is a policy
nobody has tested against reality. The signal is a later phase writing its own
re-check loop rather than reading `RecheckPolicy` — at which point this is a
constant with a test and no reader, and should be deleted rather than kept for
symmetry.

**Confidence.** High on the mechanism, which is a declared field and a validated
bound over machinery that already worked. Moderate on the specific eleven-seven
split: it is defensible for each row, and it has never been tested against a process
that ran long enough to be wrong about one.

## References

- [ADR-0079](0079-phase-030-widens-to-deliver-the-configuration-evidence-surface.md)
  — the phase this is half of.
- [ADR-0056](0056-phase-021-widens-to-deliver-the-application-bootstrap.md) — the
  registry this extends.
- [`docs/engineering/PREFLIGHT_SUITE.md`](../engineering/PREFLIGHT_SUITE.md) — the
  classification, the schedule, and what is deliberately not run.
- [`docs/engineering/BOOTSTRAP.md`](../engineering/BOOTSTRAP.md) — the checks
  themselves.

## Supersedes

None.

## Superseded By

None.
