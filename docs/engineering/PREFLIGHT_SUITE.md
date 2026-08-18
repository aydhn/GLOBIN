# Preflight Suite

Which checks must pass before a long-running GLOBIN process starts, which of their
answers survive the run, and how often the rest are taken again.

[`BOOTSTRAP.md`](BOOTSTRAP.md) owns the *checks*: what each one measures, what it
concludes, and which exit code it declares. This owns the layer above — the
classification Phase 030 added to the registry, and the schedule that follows from
it. The split is [ADR-0080](../adr/0080-a-check-declares-whether-its-answer-survives-the-run.md)'s.

---

## Why a suite is not a longer registry

Phase 021 built a registry. Eighteen checks, performed in order, reduced to one exit
code by the earliest refusal. For a command that reports and exits that is complete,
because the instant its answers describe and the instant the process ends are the
same instant.

`ROADMAP.md` row 030 asks for the checks that must pass before any **long-running**
process starts, and that adjective breaks the identity. A gate that passed an hour
ago is a claim about an hour ago. Some of what the eighteen checks measure cannot
have moved since; some of it moves as a matter of ordinary operation. Nothing in the
registry could say which was which, and a schedule is undefinable without that.

---

## Durability

Every registered check declares one of two values, beside the exit code it already
declares.

| Value | Meaning |
|---|---|
| `STABLE` | The answer cannot change while this process runs. Taking it once is taking it for the run. |
| `PERISHABLE` | It was true when taken, and may since have stopped being true. |

**The line is drawn at who changes the thing being measured.** An operating system,
an interpreter, an architecture and a set of installed distributions are changed by
an operator doing something deliberate outside GLOBIN, and a process that saw one
change under itself has larger problems than a stale check. Free space, a
directory's existence and an exclusive lock are changed by ordinary operation — by
GLOBIN, by another process, by anything on the machine.

**The default is `PERISHABLE`.** A nineteenth check whose author did not think about
the question costs a re-measurement nobody needed; the opposite default would let an
unconsidered answer be believed for ever.

### The eighteen

| Check | Durability |
|---|---|
| `project.root` | `STABLE` |
| `runtime.host` | `STABLE` |
| `runtime.architecture` | `STABLE` |
| `environment.capability` | `STABLE` |
| `python.implementation` | `STABLE` |
| `python.version` | `STABLE` |
| `python.environment` | `STABLE` |
| `project.identity` | `STABLE` |
| `dependency.lock` | `STABLE` |
| `config.valid` | `STABLE` |
| `paths.runtime` | `PERISHABLE` |
| `paths.boundary` | `PERISHABLE` |
| `state.persistence` | `PERISHABLE` |
| `state.previous_run` | `STABLE` |
| `instance.lock` | `PERISHABLE` |
| `runtime.degradation` | `PERISHABLE` |
| `secrets.required` | `PERISHABLE` |
| `secrets.entitlement` | `PERISHABLE` |
| `bootstrap.ready` | `PERISHABLE` |

Eleven stable, eight perishable. The table is a restatement of `checks()`, and
`tests/contract/test_preflight_contract.py` compares the two in both directions, so
a row that drifts fails the suite rather than misleading a reader.

**Three of the calls are worth reading twice.**

- **`config.valid` is stable because the snapshot is immutable**, not because
  documents are. An operator may edit `config/` while GLOBIN runs; the process is
  not reading it again, so the values this check judged are the values it will use
  until it stops. That is Phase 007's design showing through rather than an
  assumption about operator behaviour.
- **`state.previous_run` is stable because it asks about history.** The previous run
  ended before this one began, so its record cannot change — and re-taking the check
  later would read *this* run's record, answering a different question under the
  same name.
- **`bootstrap.ready` is perishable because an aggregate is no stronger than its
  weakest input**, and seven of its inputs decay.

---

## The schedule

`RecheckPolicy` declares how often a perishable answer is taken again.

| Bound | Value | Why |
|---|---|---|
| Floor | 1 000 ms | Below it the probes stop being cheap: `paths.runtime` asks the filesystem for free space and `instance.lock` attempts an exclusive acquisition. |
| Default | 60 000 ms | Deliberately far slower than the watchdog's second. |
| Ceiling | 3 600 000 ms | Beyond it the schedule is the start-up verdict with extra machinery. |

**A policy that could not be honoured cannot be constructed.** The bounds are
checked where the policy is declared rather than where a scheduler would read them,
which is the treatment `RotationPolicy` and `WatchdogPolicy` already receive. A
`bool` is refused even though Python makes it an `int`, because `True` resolving to
an interval of one millisecond is the kind of accident that looks like it worked.

**The interval is a constant, not a setting.**
[`../CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md) asks a proposed setting to
have a call site in the phase that adds it, and this one has none. The phase that
runs a schedule may reasonably promote it.

**Why not the watchdog's interval.** The two answer different questions at different
rates. The watchdog asks whether a component is still moving, where a sub-second
answer is the entire value; this asks whether the host is still fit, where nothing
an operator can act on changes that fast. Sharing the number would couple them, and
the first phase to change one would silently change the other.

---

## Nothing runs it

**No re-take is executed anywhere, and that is the deliberate half.** GLOBIN has no
long-running process. The phase that starts one honours this policy; until then a
scheduler would be a mechanism with no caller, tested only against itself — which is
how a repository acquires code that works until the day something calls it.

What is delivered instead is a policy that cannot exist in an unhonourable form, and
a verdict that can say how long it is good for.

---

## The command

```bash
.venv\Scripts\globin.exe bootstrap preflight
```

**The third combination of two switches that already existed, not a fourth
pipeline.** `bootstrap check` stops at the first refusal and gates; `doctor` runs
everything and reports. A launcher about to start a long-running process needs both
halves — every fault in one pass, and a refusal — and it needs the sentence neither
can say.

The report marks a perishable pass with `~` in the check table rather than only
summarising it below, because an operator scanning the column is the reader the whole
classification exists for.

```text
  PASS       config.valid              bound, logging at DEBUG
  PASS       instance.lock           ~ the coordinator lock is available to this process

~ marks 7 answer(s) that were true when taken; take them again every 60000 ms.
GLOBIN may start.
```

**It introduces no exit code.** A preflight refusal is already describable by the
failing check's own code, which `CheckSpec` declares once. Code 26 stays free.

Under `--json` the document carries the verdict, the suite, what decays and every
check, built by the domain so that the stream and any later artefact describe one
run rather than two renderings of it.

---

## What this does not cover

| Question | Phase |
|---|---|
| What each check measures and what its exit code means | 021, delivered — [`BOOTSTRAP.md`](BOOTSTRAP.md) |
| Behaviour when the network, GPU or optional native components are unavailable | 031, delivered — [`DEGRADED_OPERATION.md`](DEGRADED_OPERATION.md) |
| Whether the band's phases are drawn at the right granularity | 032 |
| Blocking a **live** launch on connectivity, credentials and risk | 297 |
| A process that runs long enough to need a re-take, and the loop that performs it | 297 and beyond |

**Phase 297 is the boundary worth stating plainly**, because its title is *Preflight
Verification Gate*. It is not this gate. This suite is local: it reaches no network,
contacts no venue and knows nothing about risk. Phase 297 inherits this
classification rather than replacing it.

---

## Related documents

- [`BOOTSTRAP.md`](BOOTSTRAP.md) — the checks themselves, and the exit-code table.
- [`RUNTIME_WATCHDOG.md`](RUNTIME_WATCHDOG.md) — the other thing that looks
  repeatedly, and asks a different question.
- [ADR-0080](../adr/0080-a-check-declares-whether-its-answer-survives-the-run.md) —
  the decision.
- [ADR-0079](../adr/0079-phase-030-widens-to-deliver-the-configuration-evidence-surface.md)
  — the phase this is half of.
