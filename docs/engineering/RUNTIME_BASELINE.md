# Runtime Baseline

Which Windows host, which CPython and which environment GLOBIN is developed and
verified on, how to build that environment, and how to diagnose one that is wrong.

The decision behind all of it is
[ADR-0050](../adr/0050-the-runtime-is-a-declared-contract-and-venv-is-its-only-environment.md).
The values are in
[`runtime-contract.toml`](runtime-contract.toml) and are not restated here —
this document explains and points, per
[`DOCUMENTATION_STANDARD.md`](DOCUMENTATION_STANDARD.md).

---

## The short version

```bash
powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
```

Run that once. Then everything else works, and nothing needs activating.

---

## What is required

| Requirement | Where it is declared |
|---|---|
| Windows 10 or newer, 64-bit | `[host]` in `runtime-contract.toml` |
| CPython on the declared minor line, at or above the declared patch floor | `[interpreter]` |
| A 64-bit AMD64 interpreter | `[interpreter]` |
| A final release — not a release candidate | `[interpreter]` |
| The default build — not free-threaded | `[interpreter]` |
| A `.venv` at the repository root, without the global site directory | `[environment]` |

Nothing in that table is a number this document owns. Read the contract for the
values; a copy here would be a copy that falls out of date.

**The patch is a floor, not an exact pin.** Anything later in the same minor line
passes, so installing a security patch does not break the build. Anything on
another minor line does not, so the day a new Python arrives is a day to run the
gates and decide. The reasoning is ADR-0050 §2.

**`requires-python` in `pyproject.toml` is a different fact** and is deliberately
wider. It states what the *package* supports, on evidence about the libraries
later phases will need. The runtime contract states what the *development and
verification host* must be. A contract test asserts the second sits inside the
first, so they can never contradict each other.

---

## Building the environment

```bash
powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
```

It resolves the repository from its own location, so the working directory does
not matter and neither does the drive. It:

1. checks this host and this interpreter against the contract, and **refuses to
   build anything from an interpreter that fails it**;
2. creates `.venv` if it is absent, from that interpreter;
3. installs the development toolchain — the same versions
   `.github/workflows/` pins, read from there rather than declared again;
4. re-runs the read-only check *through the new environment*, so the evidence it
   leaves describes the environment rather than the interpreter that built it.

Run it twice and the second run creates nothing. That is the point of it.

### Using a different interpreter

```bash
powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1 -Interpreter "C:\Python314\python.exe"
```

The contract is checked against whatever you pass before anything is created, so
pointing this at the wrong Python produces a refusal rather than a wrong
environment.

### Rebuilding from scratch

```bash
powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1 -Recreate
```

`-Recreate` removes the environment first. It is refused unless the target
resolves to exactly the declared directory at the repository root and is not a
symbolic link or junction. That decision is made in Python, in
`tools/quality/runtime/plan.py`, where tests hold it — no recursive delete is
composed from a variable anywhere in `scripts/`.

---

## Diagnosing a host

```bash
powershell -ExecutionPolicy Bypass -File scripts/preflight.ps1
```

Read-only. It creates nothing, installs nothing, and changes no host setting. Use
it before bootstrapping to find out what is wrong, and afterwards to confirm
nothing has drifted.

It writes `.globin/runtime/runtime-manifest.json`, which is the same document
continuous integration uploads.

The same check is a quality command, and this is what CI runs:

```bash
python -m tools.quality runtime
```

Exit codes are the ones every gate here uses: `0` passed, `1` a check failed, `2`
the command line was not understood, `3` a check could not be measured — which is
never a pass.

---

## Automation never activates the environment

Activation exists for humans:

```bash
.venv\Scripts\activate.bat
```

```bash
.venv\Scripts\Activate.ps1
```

It is optional, and **nothing in this repository depends on it**. Every script and
every gate addresses `.venv\Scripts\python.exe` directly, so `PATH` order, a stale
shell and a forgotten activation cannot change which interpreter runs.

To run anything yourself:

```bash
.venv\Scripts\python.exe -m tools.quality full
```

`scripts/verify.ps1` does this for you, and **refuses to run without an
environment**. There is no fallback to an interpreter on `PATH`: a fallback would
be used on exactly the day the environment was wrong, which is the day the gate's
answer matters most.

---

## Diagnosing each finding

Every finding names the problem. This is what to do about it.

### `interpreter` — the wrong Python

The message names both what was found and what the contract requires. Common
causes:

- **Wrong minor line.** `PATH` resolved a different interpreter. Check with
  `where python`, and pass the right one with `-Interpreter`.
- **Wrong patch.** The interpreter is older than the verified baseline. Install a
  newer patch of the same line from `https://www.python.org/downloads/`.
- **32-bit.** The 32-bit installer was used. Reinstall the 64-bit one; the
  download page marks it *Recommended*.
- **Free-threaded, or a prerelease.** Use the default build of a final release.
  Both refusals are provisional on the wheel-availability survey in Phase 018.

### `environment` — the `.venv` is wrong

- **"does not exist"** — run `bootstrap.ps1`.
- **"--system-site-packages"** — the environment can see the machine's global
  packages, which makes its contents depend on the machine. Rebuild with
  `-Recreate`.
- **"created from Python X"** — the environment was built by an interpreter the
  contract refuses. Rebuild with `-Recreate`, from the right interpreter.
- **"stale"** — the base interpreter it was built from is gone, usually because
  Python was upgraded in place. Rebuild with `-Recreate`.
- **"moved or copied"** — the environment, or a parent directory, was moved.
  `venv` does not support this, and the failure is quiet: the interpreter still
  runs and only the console scripts misbehave. Rebuild with `-Recreate`.

### `running_interpreter` — the check ran from the wrong Python

The gate was invoked by an interpreter that is not the project environment's, so
what it measured is not what `.venv` contains. Use `preflight.ps1`, or invoke it
as `.venv\Scripts\python.exe -m tools.quality.runtime`.

### `pip_origin` — `pip` belongs to another interpreter

`pip install` would write somewhere other than this environment — before Phase
017 on this host, into a user-level directory shared with every other project on
the machine. Run the gate through the environment's interpreter. **Never use a
global `pip install` for this project**: it installs for every project at once,
and nothing records that it happened.

### `host` — the operating system

Windows 10 is the floor, and it is the floor because it is the strictest one
among the libraries later phases need. The comparison is against the *kernel*
version rather than the release name, because release names do not order —
Windows Server reports a year, so `"2019"` sorts above `"11"` while being older.

---

## Host problems the gate reports and does not fix

Nothing here changes your machine. No registry key is written, no `PATH` is
edited, no execution policy is relaxed, and no runtime is installed unless you
ask for one. A tool that silently reconfigured the machine it was diagnosing
would have destroyed the evidence it was run to collect
([ADR-0045](../adr/0045-a-platform-capability-is-a-recorded-state-never-a-pass.md)).

### PowerShell refuses to run the scripts

The documented invocation passes `-ExecutionPolicy Bypass`, which applies to that
one process and changes nothing durable. If a machine policy still blocks it, the
remedy is your administrator's, and Microsoft documents the policies at
`https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_execution_policies`.

### Long paths are disabled

Recorded under `capability.long_paths` as `enabled`, `disabled` or `unmeasured`.
Enabling them is a machine-wide change requiring administrator rights: the *Enable
Win32 long paths* group policy, or `LongPathsEnabled` under
`HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\FileSystem`.

Nothing in GLOBIN needs them yet. It is recorded now so the phase that first
writes a deep artefact tree inherits the fact rather than discovering it.

### Two Pythons, or two `py.exe`, on `PATH`

`where python` and `where py` list them. This is not an error and the gate does
not treat it as one — it is the reason the project uses an environment rather
than trusting `PATH`. The launcher and the runtimes it can see are recorded under
`observed.discovery`.

### There is no Python install manager

The manager is the modern way to install runtimes on Windows, and `--install-python`
needs it. Where only the legacy `py.exe` is present, `py list` and `py install`
do not exist, and the gate records that rather than failing.

Enabling the manager means uninstalling **Python Launcher** from *Installed apps*
and installing the manager from `https://www.python.org/downloads/`. That is a
change to your machine, so it is yours to make.

### A `pip.ini` or a `PIP_*` variable is set

Recorded under `observed.pip` as which scopes exist and which variables are set
**by name**. Never a path, and never a value: an index URL is the likeliest place
in this document for a credential to appear, and the way to keep one out is not to
read it. If a build installs something unexpected, that record is where to look
first.

---

## `.venv` is never committed

It is disposable local state — not a build artefact, not something to copy to
another machine, and not something to commit. `.gitignore` has carried `.venv/`
since Phase 001, before there was anything to ignore, and `venv` additionally
writes a self-ignoring `.gitignore` inside the directory. A contract test asserts
both that the rule is there and that nothing under it is committable.

If you need it somewhere else, recreate it there.

---

## What this does not cover

| Question | Owner |
|---|---|
| Which libraries have wheels for the pinned interpreter | Phase 018 |
| Runtime dependencies, and the lock that must accompany the first one | Phase 021 |
| Runtime configuration, and credential onboarding | Phases 021-032 |

**What `bootstrap` installs changed in Phase 020.** It was the exact versions the
workflows pin -- seven direct tools, with the forty-two they resolve to left to
whatever an index served that day. It is now `pylock.dev.toml`, hash-checked, and
an unreadable lock is a refusal rather than a fall back to the pins. `--from-pins`
restores the previous behaviour as a deliberate act, because
`pip install -r pylock.toml` is labelled experimental upstream and this is the one
command somebody runs before they have a working tree. See
[`DEPENDENCY_LOCKING.md`](DEPENDENCY_LOCKING.md) and
[ADR-0054](../adr/0054-the-toolchain-is-locked-with-pep-751-and-the-verdict-is-recomputed.md).

**Drift over time is no longer deferred.** Phase 019 delivered it as a separate
gate, because it asks a different question from this one: this document's checks
ask whether the host is *acceptable*, and that one asks whether the host is *what
it was*. The two disagree wherever the contract is deliberately loose — an
interpreter whose patch went backwards satisfies the floor above and has still
been changed by somebody. See [`ENVIRONMENT_DRIFT.md`](ENVIRONMENT_DRIFT.md).

That gate also corrects one piece of advice given above. *Diagnosing each finding*
answers five distinct `environment` faults with "rebuild with `-Recreate`". Four
of them need it. `--system-site-packages` does not: `pyvenv.cfg` is read at
interpreter start-up, so `python -m tools.quality.drift repair` corrects it by
rewriting one key.

---

## Related

- [ADR-0050](../adr/0050-the-runtime-is-a-declared-contract-and-venv-is-its-only-environment.md) — the decision.
- [ADR-0051](../adr/0051-phase-017-absorbs-interpreter-pinning-and-the-environment-lifecycle.md) — why one phase delivered what three were scheduled to.
- [`runtime-contract.toml`](runtime-contract.toml) — the declaration itself.
- [`QUALITY_GATES.md`](QUALITY_GATES.md) — every command, including this one.
- [`../research/phase_017_sources.md`](../research/phase_017_sources.md) — every external claim above, with its source.
