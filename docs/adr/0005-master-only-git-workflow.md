# ADR-0005 — Master-only Git workflow

## Status

Accepted — Phase 001.

## Context

GLOBIN is developed across 320 phases, largely by coding agents working in
separate sessions with no shared memory. Branching models that work well for
human teams — feature branches, pull requests, review queues — depend on
participants who remember open work and return to finish it. An agent that
creates a branch and ends its session leaves work that nobody is aware of.

The failure mode is concrete: an agent creates a branch, commits there, reports
success, and the next agent starts from a repository that does not contain that
work. Two sessions later there are divergent histories nobody reconciles.

There is a second hazard specific to this project. Most Git hosting now defaults
new repositories to a branch named `main`. If any tooling or documentation
quietly assumed that default, the project would end up with two long-lived
branches and no clear source of truth.

## Decision

**All GLOBIN development happens on `master`, and only on `master`.** This is
encoded as `REQUIRED_GIT_BRANCH = "master"` and asserted by contract test.

Every completed phase must end with tests passing, documentation synchronized, a
meaningful commit on `master`, a successful push to `origin/master`, and a clean
working tree. A phase is not complete until its work is visible on the remote.

The project must never create or switch to a branch named `main`, nor to
development, feature or temporary branches. Because the remote repository was
empty when Phase 1 initialised it, the first push established `master` as the
default branch, so no alternative branch has ever existed.

To keep this from eroding, `tests/test_documentation_contract.py` scans the
authoritative Git documentation for command-shaped instructions referencing an
alternative branch and fails if any appear.

## Consequences

- History is linear and unambiguous. The remote is always the current truth.
- No work can be stranded on an unmerged branch.
- The cost is that broken intermediate states are more visible, so verification
  must run *before* committing rather than after. `scripts/verify.ps1` exists
  for exactly that reason.
- Agents cannot rely on a review gate to catch mistakes. The test suite is the
  gate, which raises the value of the contract tests considerably.
