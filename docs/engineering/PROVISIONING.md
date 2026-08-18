# Provisioning

How an operator gets from a clean Windows machine to a GLOBIN that will start,
and what each step is permitted to change.

---

## Start here, and read this paragraph first

**`globin bootstrap setup` is not the cold-start path.** It is installed *into*
the environment it would create, so it cannot be how that environment first
appears. The first command on a new machine is, and remains:

```bash
powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
```

What the provisioning verbs are for is **completing and repairing** an
environment that already has a `globin` in it — the case where something has gone
wrong since, or where a run was interrupted part-way. That is the honest scope,
and it is what makes the interruption marker worth having rather than decorative.

---

## The operator flow

| Step | Command | Changes anything? |
|---|---|---|
| 1 | `powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1` | Yes — creates `.venv` |
| 2 | `globin bootstrap check` | No |
| 3 | `globin bootstrap plan` | No |
| 4 | `globin bootstrap setup` | Yes — only what the plan named |
| 5 | `globin secrets set …` | Yes — and only an operator can do it |
| 6 | `globin bootstrap preflight` | No |
| 7 | `globin doctor` | No |

Steps 2 and 3 answer different questions. `check` says **what is wrong**;
`plan` says **what would be done about it**, in the order it would be done, with
what each action costs. Neither writes anything.

`globin bootstrap evidence` writes the bootstrap manifest, and is the one
read-only-ish verb that produces a file rather than a stream.

---

## The verbs

| Verb | What it does | Mutates |
|---|---|---|
| `bootstrap check` | Refuse to start unless every check passes. Stops at the first refusal. | No |
| `bootstrap plan` | Say what would change, and what it would cost. | No |
| `bootstrap setup` | Bring missing pieces into existence. | Yes |
| `bootstrap repair` | Correct what exists and is wrong. | Yes |
| `bootstrap preflight` | Run every check, gate, and say which answers decay. | No |
| `bootstrap evidence` | Write the bootstrap manifest. | Writes evidence only |

**There is no `verify`.** It is the obvious name for "run every check and gate",
and that is exactly what `bootstrap preflight` already is — and the word is
already taken at this repository's shell by `scripts/verify.ps1`, which means
something else. Typing it produces a refusal that names the replacement rather
than a bare "unrecognised argument".

---

## What `plan` prints, and how to read it

Each action names three things an approver is deciding about: its **mutation
class**, whether it is **destructive**, and what it **needs**.

```text
Plan (offline), 1 action(s):
  environment.create     [create]
    python.environment did not pass
    then: python.environment passes; on interruption: resumable
```

- **mutation class** — `create`, `install`, `remove` or `record`.
- **destructive** — appears only for `environment.recreate`, the one action that
  can lose work.
- **needs** — `cache` where a local wheelhouse is required. Absent means the
  action needs nothing outside this machine.
- **on interruption** — `resumable` means running it again finishes the job;
  `restart-required` means the target is left unusable and must be rebuilt.

A plan under a policy that forbids one of its actions says so rather than
dropping it, because a plan that looks complete and is not is worse than one that
names what it could not attempt.

---

## The network policy

Declared by you, never probed. GLOBIN does not test connectivity to decide what
it may reach.

| `--network` | What may be reached |
|---|---|
| `offline` *(default)* | Nothing outside this machine, and no cache. |
| `cache-only` | A local wheelhouse. Still nothing leaves the machine. |
| `online-allowed` | An index. |

The default is `offline` on purpose: the one command that mutates a host must not
also be the one that reaches the network without being asked.

```bash
globin bootstrap plan --network cache-only
```

---

## What provisioning will never do

Each of these is a refusal with a test behind it, not a habit.

- **Install a Python runtime.** That already exists, behind its own opt-in, in
  `scripts/bootstrap.ps1 -InstallPython`. This host carries the legacy `py`
  launcher, which cannot install; the install manager can, and enabling it means
  uninstalling "Python Launcher" from Installed apps, which no phase has done.
- **Write a credential, or a configuration document.** No action may answer for a
  `secrets.*` or `config.*` check, and `ActionSpec` refuses to construct one that
  does. Credentials are collected at a console by `globin secrets set`.
- **Install through WinGet.** Its presence is *detected* and published, so a later
  phase inherits a measurement rather than a guess. Nothing invokes it.
- **Ask for administrator rights.** No declared action requires elevation, and
  nothing triggers a UAC prompt.
- **Change a machine-wide setting.** No registry write, no `PATH` change outside
  this process, no execution-policy change, no environment variable that outlives
  the run.
- **Reach a shell.** `CommandRequest` has no `shell` field — not one defaulting to
  false, no field at all — and refuses shell metacharacters in construction.

---

## Idempotency

Running `setup` twice over an unchanged host does nothing the second time. The
plan is empty, the journal records `satisfied` rather than `applied`, and the
manifest is byte-identical because it carries no timestamp.

If the second run reports `applied`, something changed between them — that is a
finding, not noise.

---

## Interruption, and why a false READY is unreachable

A mutating run writes a **claim** before the first change and removes it only
after the last one completes. A process ended between the two — Ctrl+C, a crash,
a Windows shutdown — leaves the claim behind.

The next `bootstrap plan` says so:

```text
INCOMPLETE  a previous run was interrupted part-way and left a claim behind.
            `globin bootstrap repair` clears it.
```

Two properties follow, and both are structural rather than careful:

- **No `after` report is taken on an incomplete run.** `ProvisioningOutcome`
  refuses to carry one, so a caller cannot get a clean verdict by ignoring the
  part that says the run did not finish.
- **The claim is not trusted for its contents.** Reading it tells a caller a run
  was interrupted; the plan is re-derived from a fresh measurement rather than
  rebuilt from a document a process that did not finish wrote.

---

## Concurrency

A mutating run holds a lock named `provisioning.lock`, in the same runtime area
as the coordinator's `instance.lock` and deliberately **not** that lock. The
coordinator's is a whole-application mutex; a `setup` holding it would make its
own `instance.lock` check fail against itself.

`check` and `plan` take no lock and can run beside anything.

---

## Troubleshooting

### The environment does not exist yet

`bootstrap setup` cannot be your first command — it lives in the environment it
would create. Run `scripts/bootstrap.ps1`.

### `python.environment` fails and `setup` does not fix it

The environment exists but is not the project's. `setup` creates a missing one; it
does not replace a wrong one, because replacing means deleting and that needs your
intent:

```bash
globin bootstrap repair --recreate
```

Run `globin bootstrap plan --recreate` first to see what that would delete.

### A previous run was interrupted

`globin bootstrap repair`. The claim is cleared once the run completes.

### `dependency.install` is refused

The default policy is `offline` and installing needs a cache. Either populate the
wheelhouse and use `--network cache-only`, or run
`python -m tools.quality materialize` to find out what is missing.

### PowerShell refuses to run the script

Your execution policy forbids it. **Nothing here changes that for you**, and no
document should tell you to. The supported route is the one the wrapper already
takes — address the interpreter directly:

```bash
.venv\Scripts\python.exe -m tools.quality.runtime bootstrap
```

If a Group Policy sets the execution policy, that is your organisation's setting
and GLOBIN does not attempt to work around it.

### There is no Python launcher on this host

`plan` records it on the action rather than refusing, because whether a launcher
is needed is a question for the thing doing the work. If the environment cannot be
built, `scripts/bootstrap.ps1 -Interpreter <path>` takes an explicit one.

### The install manager and the legacy launcher disagree

Both answer to `py`, and both can be installed at once. The manager is detected by
the `pymanager` command, never by `py` existing — so a host with only the legacy
launcher is never mistaken for one that can install a runtime.

---

## Related documents

| Question | Phase |
|---|---|
| How a GLOBIN process decides it may start | 021, delivered — [`BOOTSTRAP.md`](BOOTSTRAP.md) |
| Which checks must pass, and which answers decay | 030, delivered — [`PREFLIGHT_SUITE.md`](PREFLIGHT_SUITE.md) |
| Which Windows, which Python, and how `.venv` is built | 017, delivered — [`RUNTIME_BASELINE.md`](RUNTIME_BASELINE.md) |
| Whether the lock could be installed offline | 029, delivered — [`DEPENDENCY_MATERIALIZATION.md`](DEPENDENCY_MATERIALIZATION.md) |
| How a credential is handed to GLOBIN | 029, delivered — [`../security/CREDENTIAL_FLOW.md`](../security/CREDENTIAL_FLOW.md) |
| What GLOBIN may run without | 031, delivered — [`DEGRADED_OPERATION.md`](DEGRADED_OPERATION.md) |
| Installing a Python runtime from within GLOBIN | 291 |
| Provisioning a credential without an operator at a console | 292 |
