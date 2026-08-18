# ADR-0085 — A plan is derived from a report, and one module may start a process

## Status

Accepted — Phase 032. **Date:** 2026-08-19

## Context

Phase 032 adds three verbs that answer questions the bootstrap surface could not:
what would have to change, do it, and fix what is wrong. Two of the three mutate a
host, which is a capability GLOBIN had never had, and the design question is what
stops that capability from being larger than it needs to be.

Four decisions carry the whole of it, and each is stated here because each was
available to be got wrong.

## Decision

### 1. A plan is derived from a bootstrap report and from nothing else

`plan_from` takes a `BootstrapReport`, a `NetworkPolicy` and a `HostCapability`,
and performs no measurement of its own.

Two properties follow. **`plan` and `check` cannot disagree about the host**,
because they read one report; a launcher may branch on either and get the same
answer. And **`plan` is read-only by the architecture contract** rather than by
promise: the planner lives in `globin.domain`, which
`docs/architecture/dependency-rules.toml` gives `may_perform_io = false`, so it
could not write if somebody asked it to.

A read-only wiring additionally hands the surface a runner that admits only the
three declared version probes and raises on anything else, so the property holds
in production and not only under test.

### 2. Exactly one module may start a process, and it is named

`globin.adapters.provisioning` is the one module in the package permitted to start
a child. Nothing under `src/globin` imported `subprocess` before this phase — but
that was never a rule. `dependency-rules.toml` has always listed `subprocess`
among the I/O-capable modules and always let the adapters layer perform I/O, so
this is an unbroken property becoming a bounded one rather than a contract being
widened. The layer contract needed no edit, which is evidence the tripwire is the
right shape.

`tests/architecture/test_process_discipline.py` enforces it in **both
directions**, which is the shape `test_library_discipline.py` uses for the socket
and for the same reason: a rule that no module outside the named one starts a
process is vacuously satisfied by a tree where none does.

**Writing that rule wrong first is recorded rather than tidied away.** A check
over bare attribute names flagged `HostFacts.system` — the operating system's
*name* — in seven modules that start nothing. Matching the qualified `os.system`
form costs precision against `from os import system`, which a second test covers
instead. The socket discipline made the same correction to its own neighbour.

### 3. A command is a value type that cannot express a shell

`CommandRequest` holds an executable and an argument vector. There is **no
`shell` field** — not one defaulting to `False`, none at all — so a caller cannot
ask for a shell because the type cannot describe one. Shell metacharacters are
refused in construction rather than escaped, because escaping is something
somebody has to get right every time and refusing is something that is right
once.

This is the shape `LoopbackAddress` uses in `globin.domain.diagnostics_http`: the
dangerous value is made unrepresentable rather than policed.

The rule caught a real call while the tests were being written. A timeout test
reached for `import time; time.sleep(30)` and was refused for the semicolon,
which is exactly the case the rule exists for — the semicolon means nothing to an
argument vector and everything to a shell, so writing one is evidence the caller
believes it is composing a shell command.

### 4. A child's output is never published

`CommandResult.as_record` carries which command, which exit code and **how many
bytes** each stream held. It does not carry the text.

`globin.domain.observability.redact` matches field *names*. A child's standard
output is not a name GLOBIN chose — it is text GLOBIN did not write, arriving
under a key (`stdout`) that matches no sensitive fragment. Passing it through the
redactor would look like a protection and be none: a tool echoing an environment
variable would have published a credential verbatim.

GLOBIN cannot know what a child printed, so it records what it does know. The
text goes to the operator's terminal, which is where it is useful and is not a
document anybody forwards.

### 5. An action declares who performs it

The packaging forced this, and the packaging is the evidence. GLOBIN's wheel holds
`globin/` and its `.dist-info` and nothing else — measured, in `ENV-C-04` — so an
installed GLOBIN has no `tools/` to invoke and no `scripts/` to run. An executor
that shelled out to either would work from a source checkout and fail everywhere
else, which is the worse of the two because it looks correct to whoever wrote it.

`ActionSpec.performer` is `GLOBIN` or `OPERATOR`. The plan shows both, because an
operator needs to see everything standing between them and a working host, and an
action that is the operator's and names no command cannot be constructed.

## Consequences

**No fifth `CheckStatus` member.** The brief asked for `BLOCKED` and `SKIPPED`.
`UNMEASURED` already means what `BLOCKED` means — `foundation-acceptance.toml`'s
own header says the gate maps one onto the other — and `SKIPPED` is a statement
about an action rather than a measurement. Actions got a disjoint `ActionOutcome`,
whose `SATISFIED` asserts a postcondition holds rather than describing what a
scheduler did. That distinction is what an idempotency test turns on.

**No twenty-sixth exit code.** Every refusal maps onto one that exists: an
incomplete environment is `ENVIRONMENT_MISMATCH`, whose published sentence — this
is not the project's own environment — is exactly true of a half-built one. A
code whose only honest readiness mapping is `UNKNOWN` is what Phase 031 refused to
add, and `26` stays free.

**No `verify` verb.** `bootstrap preflight` already runs every check and gates,
and the word is taken at this repository's shell by `scripts/verify.ps1`. Typing
it produces a refusal naming the replacement, and a contract test asserts the
replacement is a command line that parses, so the redirect cannot rot.

**A duplicate found while testing.** `dependency.install` and `dependency.repair`
both answered `dependency.lock` and both invoked one command, so a failing lock
planned one job twice. The second is gone, `MutationClass.REPAIR` with it — a
class with no member is vocabulary rather than a capability — and a test now
refuses two non-destructive actions sharing a postcondition.

## Alternatives Considered

**Escape shell metacharacters rather than refusing them.** Rejected: escaping is
correct only if every call site does it, and nothing here reaches a shell anyway,
so a metacharacter arriving is evidence of a caller's mistaken belief rather than
a value to sanitise.

**Pass a child's output through the redactor and publish it.** Rejected once
measured. `stdout` matches no fragment, so the redaction is inert and the
publication is real.

**Give `repair` a mutation class of its own.** Rejected after the duplicate was
removed: the only repair GLOBIN can perform is on its own runtime tree, and a
class with no member names a capability nothing has.

**Add a `26` for "provisioning incomplete".** Rejected under Phase 031's rule.

## Risks and Trade-offs

**Byte counts are a weaker diagnostic than text.** An operator debugging a failed
child must run it themselves. That is stated in the step's own detail rather than
left to be discovered.

**The process tripwire is a proxy.** A module handed an open pipe would defeat it,
exactly as a module handed an open socket defeats its neighbour.

**`setup` is not the cold-start path**, and its name suggests otherwise.
`PROVISIONING.md` opens with that sentence and a contract test asserts the
document names `scripts/bootstrap.ps1`.

## References

- [`../engineering/PROVISIONING.md`](../engineering/PROVISIONING.md)
- [`../architecture/dependency-rules.toml`](../architecture/dependency-rules.toml) — permits `subprocess` in adapters, unchanged by this phase.
- [ADR-0072](0072-the-diagnostics-surface-is-loopback-only-read-only-and-bounded-by-construction.md) — the value type that refuses to widen, which `CommandRequest` follows.
- [ADR-0084](0084-phase-032-widens-to-deliver-the-bootstrap-provisioning-surface.md) — the amendment carrying these decisions.

## Supersedes

Nothing.

## Superseded By

Nothing.
