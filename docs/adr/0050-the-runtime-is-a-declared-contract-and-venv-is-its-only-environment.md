# ADR-0050 — The runtime is a declared contract checked against the host, and `.venv` is its only environment

## Status

Accepted — Phase 017.

## Context

For sixteen phases GLOBIN was developed against whichever `python` the `PATH`
resolved first, with its toolchain installed at user level and no virtual
environment at all. Every gate passed. None of them named an interpreter.

That is not a hypothetical weakness. The development host carries two
interpreters and two launchers on `PATH`:

```text
C:\Python314\python.exe
C:\Users\<account>\AppData\Local\Programs\Python\Python312\python.exe
C:\Windows\py.exe
C:\Users\<account>\AppData\Local\Programs\Python\Launcher\py.exe
```

and `pip` resolves to a **user-site** installation
(`AppData\Roaming\Python\Python314\site-packages`) rather than to anything the
project owns. So "the tests passed" meant "the tests passed under whatever won a
`PATH` search", and nothing in the repository would have noticed the day that
changed. `pip install` in this repository's directory would have written into a
directory shared with every other project on the machine.

Three further facts shaped what could be decided here.

**The host does not have the Python install manager.** It has the legacy
`py.exe`, which supports `-V:3.14` but has no `py list` and no `py install`. The
manager's own documentation says the legacy launcher takes precedence for the
`py` command and must be uninstalled from *Installed apps* to enable the new one.
That is a change to the machine, and this phase does not make changes to the
machine.

**The host runs CPython 3.14.5, and 3.14.7 exists.** 3.14 is in bugfix status and
3.14.7 was released on 2026-08-05, ten days before this phase. The owner directed
that the baseline be what is installed, and that no new installation be required.

**`requires-python` already exists and means something else.** `pyproject.toml`
declares `>=3.12`, and that floor is evidence-based: XGBoost, scheduled for Phase
182, is the strictest constraint among the planned stack. It is a statement about
what the *package* supports. It is not a statement about which interpreter the
gates were actually run on, and conflating the two would either weaken the
package's declared range or overstate what has been measured.

## Decision

### 1. The runtime baseline is declared in one file, and compared against the host

`docs/engineering/runtime-contract.toml` states the implementation, the minor
line, the patch floor, the architecture, the interpreter width, whether a
free-threaded build or a prerelease is acceptable, the operating system, its
release floor, the environment's directory name, and whether the global site
directory may be visible.

Nothing generates it. A manifest generated from the host could only ever agree
with the host, which is a mirror rather than a check — the argument
`docs/engineering/governance.toml` already makes about itself.

It is a **second** declaration alongside `requires-python`, not a duplicate of
it, because the two answer different questions. A contract test asserts the
baseline satisfies `requires-python`, so the two can be narrower and wider than
each other but never contradictory.

### 2. The patch is a floor, not an exact pin

`minimum_patch = "3.14.5"`. Anything later in the 3.14 line passes; 3.13 and 3.15
do not, and neither does 3.14.4.

An exact pin was considered and rejected. It fails the build on the day a
security patch is installed, which is the day that failure is least welcome, and
a pin that is re-derived from whatever happens to be installed the first time
that becomes inconvenient has become a mirror again. Requiring only the minor
line was also rejected: it would accept a patch nobody had run the gates against.

The minor line, by contrast, **is** exact. A repository verified on 3.14 has not
been verified on 3.15, and the day 3.15 arrives is the day to run the gates and
decide rather than to have already silently accepted it.

### 3. A free-threaded build and a prerelease are refused, and that is not a judgement about either

`free_threaded = false` and `allow_prerelease = false`. Neither is a claim that
those builds are bad. The free-threaded build has a different ABI and a different
wheel set, and **Phase 018 has not yet surveyed whether the planned stack
publishes for it** — refusing it is a refusal to assume an answer nobody has
looked up. A prerelease can change behaviour before its final release, so a gate
that passed on one is evidence about a runtime that no longer exists.

### 4. The environment is `.venv` at the repository root, and automation never activates it

One directory, not configurable. A project whose environment can live anywhere is
a project where "which Python ran that" has no answer, and this host already has
enough interpreters to make that question real.

Activation is documented for humans and used by nothing. `scripts/verify.ps1`,
`scripts/preflight.ps1` and `scripts/bootstrap.ps1` all address
`.venv\Scripts\python.exe` directly, so `PATH` order, a stale shell and a
forgotten `activate` cannot change what runs.

**`verify.ps1` has no fallback to a `PATH` interpreter.** An escape hatch would be
used on exactly the day the environment was wrong, which is the day the gate's
answer matters most.

### 5. `pyvenv.cfg` is the evidence, so nothing has to be launched to judge an environment

CPython writes the creating interpreter's full three-component version into
`pyvenv.cfg`, and writes `include-system-site-packages` whether or not the flag
was passed. So an exact-patch check and a global-site-packages check are both a
file read rather than a process launch.

`Scripts\activate.bat` records the absolute location the environment was built
at, which is the only artefact inside an environment that remembers where it came
from — and therefore the only way to notice one that has been moved or copied.
`venv` states plainly that environments are "not considered as movable or
copyable"; a moved one still runs, and only the console scripts, which hold
absolute paths, misbehave.

### 6. Nothing changes the host, and a host fact that cannot be changed is recorded

No registry key is written, no `PATH` is edited, no execution policy is relaxed,
no runtime is installed unless `--install-python` is passed and a manager exists
to act on it, and nothing is ever installed into a global or user site directory.

Where a host setting is wrong, the gate reports it and names the official remedy.
Long paths are read from the registry and recorded as `enabled`, `disabled` or
`unmeasured`; the install manager's absence is recorded as a state. Both follow
[ADR-0045](0045-a-platform-capability-is-a-recorded-state-never-a-pass.md): an
absence is recorded as an absence, never rounded to a pass. A tool that silently
reconfigures the machine it is diagnosing has destroyed the evidence it was run
to collect.

### 7. Every path in the evidence is repository-relative or a fingerprint

The manifest is uploaded as a CI artifact from a public repository, and on this
host every absolute path outside the tree contains the account holder's full
name. A path inside the repository is recorded relative to it; a path outside is
recorded as a truncated SHA-256 and nothing else. There is no third option, and
in particular none that writes the path out.

`pip` configuration is recorded as **which scopes exist**, never as a path and
never as a value. An index URL is the likeliest place in this document for a
credential to appear, and the way to keep one out is not to read it. `PIP_*`
variables are recorded by name, because the name says an override is in force and
the value says what it is.

The gate scans its own rendered manifest before writing it, and fails on a leak
rather than publishing one.

### 8. Deleting is decided in Python, never in PowerShell

`--recreate` removes an environment only after `deletion_problems` has confirmed
the target is exactly the declared directory at the repository root, is inside the
repository, and is not a reparse point. That function is pure and tested from
literals, including against a generated set of paths.

No `Remove-Item -Recurse` is composed from a variable anywhere in `scripts/`. A
recursive delete assembled from a string in a shell script is one bad join away
from removing something that matters, and the check that prevents it belongs
where a test can hold it.

### 9. Bootstrapping installs the pins the workflows already declare

The toolchain versions are read from `.github/workflows/` through
`tools/quality/supply/inventory.py`, which already parses them. An environment
built by `bootstrap.ps1` therefore contains exactly what continuous integration
measured, and no fourth register exists for
[ADR-0044](0044-dependency-review-is-a-written-process-with-a-generated-inventory.md)'s
drift check to find disagreeing with the other three.

## Consequences

**Good.** Which interpreter ran a gate is now a recorded fact rather than an
assumption. A wrong interpreter, a 32-bit one, a prerelease, a free-threaded
build, an environment with the global site directory visible, an environment
built from the wrong patch, a stale one whose base interpreter has gone and a
moved one are each detected and named. `pip install` inside this repository can no
longer write outside it. Continuous integration builds the environment from a
clean machine with the same script a developer runs, which is the strongest
evidence available that the instructions work.

**Costs, accepted.** `scripts/verify.ps1` now refuses to run without an
environment, so every contributor must bootstrap once before the gate works at
all. That is a deliberate one-time cost in exchange for the gate meaning
something. The `.venv` directory name is spelled in three PowerShell scripts as
well as in the contract, because Windows PowerShell 5.1 has no TOML reader; the
copies are compared by a contract test and are a tripwire rather than a second
source, in the sense `docs/engineering/SOURCE_OF_TRUTH.md` describes.

**What this does not decide.** Which libraries have wheels for the pinned
interpreter is Phase 018, and is the survey that could yet change the free-threaded
and prerelease decisions above. Locking the dependency set is Phase 020. Runtime
configuration and credential onboarding are Phases 021-032. Nothing here installs
a runtime, and nothing here has contacted Binance.

## Alternatives Considered

**Pin the exact patch, as the phase brief asked.** Rejected on the owner's
direction and on its own merits. The host runs 3.14.5 and the brief named 3.14.7,
so an exact pin would have blocked the phase behind a manual installation on a
machine this phase is not permitted to change. It would also fail the build on
every future security patch. The floor keeps the guarantee that matters — nothing
older than what was measured — and drops the one that does not.

**Put the contract in `pyproject.toml` under `[tool.globin.runtime]`.**
`[tool.globin.mutation]` and `[tool.globin.workflow]` already live there.
Rejected because `docs/engineering/REPOSITORY_LAYOUT.md` distinguishes *settings*
from *contracts*: a contract states what is permitted and belongs beside the
document explaining it, which is where `governance.toml`, `action-pins.toml` and
`foundation-acceptance.toml` all sit.

**Widen `requires-python` to `>=3.14` and use it as the single source.** Rejected
because it would be a lie about the package. The 3.12 floor is evidence-based and
carries a written justification; narrowing it to describe one development host
would discard that evidence and would claim the package does not support
interpreters it does very likely support.

**Let `verify.ps1` fall back to a `PATH` interpreter when `.venv` is missing.**
Rejected. The fallback would be exercised precisely when the environment was
broken, which is when the gate's answer matters most, and a gate that quietly
measures a different interpreter from the one the project declares is not a gate.

**Parse the contract in PowerShell so the directory name has one source.**
Rejected as more machinery than the problem has: Windows PowerShell 5.1 ships no
TOML reader, and a hand-written parser for one string would be untested code in
the layer this repository deliberately keeps thin. A compared copy is cheaper and
is a pattern the repository already uses.

**Have `bootstrap` install the toolchain from the `dev` extra's lower bounds.**
Rejected because lower bounds do not reproduce: two developers bootstrapping a
week apart would get different versions, and neither would match CI. The
workflow's exact pins are what was measured.

## Risks and Trade-offs

**The floor is raised carelessly.** Someone bumps `minimum_patch` to whatever they
have installed rather than to what the tree has been verified on, and the contract
quietly becomes a mirror. The signal is a change to that line in a commit that ran
no gates on the new patch; the comment in the file says so, and the review that
catches it is the diff review in `DEFINITION_OF_DONE.md`.

**A hosted runner resolves an interpreter below the floor.** `actions/setup-python`
resolves `3.14` to the newest patch it publishes, which is at or above 3.14.5
today. If it ever resolves below one, the `runtime` job fails with
`RUNTIME_INTERPRETER_NONCOMPLIANT` and names both versions. That is a report to
act on rather than a mystery, and it is the reason the finding carries both
numbers.

**The `.venv` copies drift.** A rename touches the contract and two of the three
scripts. `tests/contract/test_runtime_contract.py` compares all four and fails;
the risk is not that it happens but that somebody deletes the comparison to make a
rename easier.

**An environment passes while being subtly wrong.** `pyvenv.cfg` is trusted, and a
hand-edited one would be believed. The mitigation is proportionate rather than
complete: the file is not a security boundary, and a contributor who edits it to
defeat a check they could simply not run has not been stopped by anything this
repository does.

**Long paths are disabled on the development host**, and this phase records that
rather than fixing it. Enabling them is a machine-wide registry change requiring
administrator rights. Nothing in GLOBIN needs them yet; the phase that first
writes a deep artefact tree will need to read this record and act.

## References

- `docs/engineering/RUNTIME_BASELINE.md` — the operational guide this record decides.
- `docs/engineering/runtime-contract.toml` — the declaration itself.
- `docs/research/phase_017_sources.md` — every external claim above, with its source.
- [ADR-0009](0009-windows-bat-launchers-as-entry-points.md) — Windows is the only declared platform.
- [ADR-0045](0045-a-platform-capability-is-a-recorded-state-never-a-pass.md) — a capability is a recorded state.
- [ADR-0048](0048-a-secret-lives-outside-the-tree-and-is-redacted-before-a-record-exists.md) — redaction before a record exists.

## Supersedes

Nothing. This is the first record about the host, the interpreter or the project
environment in GLOBIN.

It does, however, retire a claim. `CONTRIBUTING.md` stated that "Formal virtual
environment and dependency locking are the subject of Phases 17-32 and are
deliberately not solved yet". Half of that is now false — the environment is
solved and locking is not — and the sentence has been rewritten rather than left
standing.

## Superseded By

Nothing yet.
