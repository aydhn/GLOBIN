# ADR-0019 — One command table defines the checks, and every caller reads it

## Status

Accepted — Phase 004.

**Date:** 2026-08-14

## Context

Before Phase 004, the checks were a list of commands inside
`scripts/verify.ps1`. That was sufficient while the script was the only caller.
Phase 004 adds two more — a pre-commit hook and a CI workflow — and three
callers with three copies of a command list is a drift problem waiting to
happen.

The failure it produces is specific and expensive. A check added to CI but not
to the local gate breaks builds on something nobody can reproduce. A check
added locally but not to CI stops being enforced for anyone who does not run it.
Worst of all, a check dropped from one copy is invisible: everything stays
green, and the loss is discovered only when the thing it guarded breaks.

There was also a platform problem. `verify.ps1` is PowerShell, and PowerShell is
the right tool for inspecting a Windows working tree. It is the wrong place to
define what "the checks" are, because a CI runner or a hook cannot read a
`scriptblock`.

## Decision

**1. `tools/quality/commands.py` is the single definition** of every check.
`verify.ps1`, the pre-commit hook and the CI workflow all invoke
`python -m tools.quality <command>`; none keeps its own list.

**2. `tools/` is a new top-level package** for development tooling that acts on
the repository rather than being part of it. It is not `src/globin/`, which
holds production code that ships; it is not `scripts/`, which
[`REPOSITORY_LAYOUT.md`](../engineering/REPOSITORY_LAYOUT.md) reserves for
helpers that are not importable.

**3. Verification never writes.** Only `fix` and `reformat` modify the tree, and
they are named as such. No other command applies a fix, formats, or edits
anything.

**4. Failure is preserved, never summarised.** The runner returns the child
process's own exit code, stops at the first failing step, and exits with a
distinct code when a required tool is absent.

**5. Nothing is installed automatically.** A missing tool produces an actionable
error and a non-zero exit. Dependency bootstrap is Phases 017-032.

**6. Subprocesses are launched with an argument list and `shell=False`,** using
the running interpreter. No string is ever handed to a shell.

## Consequences

- Adding a check means editing one table, and all three callers acquire it.
- The gate became testable. `tests/unit/test_quality_runner.py` asserts that a
  failing step's code is propagated, that execution stops at the first failure,
  that a missing tool is distinguishable from a failed check, and that no
  verification command can modify the tree. A list of commands inside a
  PowerShell script could not have been tested at all.
- `REPOSITORY_LAYOUT.md`, `README.md` and `CLAUDE.md` gained a `tools/` entry.
  A new top-level directory is a structural change and is priced accordingly.
- `verify.ps1` shrank to what only PowerShell can do: resolve the repository
  root, run the gate, and inspect the branch and working tree.
- The quality runner is itself measured by coverage. Code that decides whether a
  gate ran must not be the untested part of the system.
- A distinct exit code for a missing tool means a CI log can never confuse "the
  gate failed" with "the gate never ran".

## Alternatives Considered

**Keep the list in `verify.ps1` and have CI call the script.** Rejected. It
would work on a Windows runner and nowhere else, it cannot be unit tested, and
it makes the definition of the checks unreadable to the hook.

**A Makefile, or `tox`, or `nox`.** Rejected on the zero-dependency and
Windows-first constraints. `make` is not present on a stock Windows host;
`tox` and `nox` are additional dependencies for orchestration this project can
express in eighty lines of typed Python that the suite already type-checks.

**Shell one-liners duplicated in each caller.** Rejected — it is the drift
problem stated as a solution.

**Put the runner in `src/globin/`.** Rejected on two grounds. It would ship a
development tool inside the distribution, and the architecture contract forbids
inner layers from importing `subprocess`, so it could only live in `adapters` or
`runtime`, where it does not belong: it is not part of the application.

**Use `argparse`.** Rejected as disproportionate. The interface is one required
word from a fixed list; hand-written parsing is about twenty lines and produces
better errors for this specific case.

## Risks and Trade-offs

The characteristic failure is the entrypoint becoming a place where logic
accumulates. It is a command table and a subprocess runner; if it grows
conditionals about which checks to run in which circumstances, it becomes a
build system nobody chose and the one-definition property quietly inverts —
callers would start passing flags to get the behaviour they want. The signal is
`runner.py` growing branches, or a caller invoking it with anything other than a
bare command name.

A second risk is the indirection itself. `verify.ps1` no longer says what it
checks, so a reader must open a second file. That is a real cost, accepted
because the alternative is three files that each say something slightly
different.

Finally, a Python entrypoint cannot check whether Python is usable. If the
interpreter is broken the gate does not run at all — but nothing else would have
either.

## References

- [`../engineering/QUALITY_GATES.md`](../engineering/QUALITY_GATES.md) — the
  command table and failure semantics.
- [`../engineering/REPOSITORY_LAYOUT.md`](../engineering/REPOSITORY_LAYOUT.md) —
  where `tools/` sits and why it is neither `src/` nor `scripts/`.
- [ADR-0015](0015-single-composition-root-and-no-import-time-side-effects.md) —
  the same one-place-decides reasoning, applied to the application.
- [ADR-0020](0020-verification-only-continuous-integration.md) — the CI workflow
  that consumes this entrypoint.

## Supersedes

None.

## Superseded By

None.
