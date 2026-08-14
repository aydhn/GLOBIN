# ADR-0017 — Test level is decided by directory, and `tests` is a package

## Status

Accepted — Phase 004.

**Date:** 2026-08-14

## Context

Before Phase 004, `tests/` was seven modules in one flat directory, all of them
contract or architecture tests. That was proportionate to Phase 003, and it
would not survive Phase 033 onwards, when integration tests against fakes and
external tests against real endpoints arrive and must be separable from checks
that run in milliseconds.

Two properties were needed. A contributor must be able to tell where a new test
belongs without asking. And a runner — the pre-commit hook, CI, or a developer
mid-edit — must be able to select a subset without relying on someone having
labelled it correctly.

A structural obstacle stood in the way. `tests/test_roadmap_contract.py` did
`from conftest import RoadmapRow`, which worked only because pytest's prepend
import mode placed `tests/` on `sys.path`. Moving a module into a subdirectory
changes the directory pytest inserts, so every such import breaks. The
convenience was never a supported interface; it was an accident of layout that
the layout was about to change.

## Decision

**1. Five levels, one directory each**: `smoke`, `contract`, `architecture`,
`unit` and `integration`, under `tests/`. `external` is defined but has no
directory, because no test at that level exists yet and
[`REPOSITORY_LAYOUT.md`](../engineering/REPOSITORY_LAYOUT.md) prohibits
directories created in advance of content.

**2. A test's directory decides its level marker.** A collection hook in
`tests/conftest.py` derives the marker from the path. No test declares its own
level.

**3. `tests` is a package**, with `__init__.py` at every level, and shared
helpers live in `tests/support.py` rather than in `conftest.py`. `conftest.py`
holds fixtures only.

**4. Attribute markers are orthogonal to levels.** `slow`, `network`, `external`
and `windows` describe a property of a test and are applied by hand. All are
registered before use.

**5. Every level holds real tests.** A level with no tests is a claim that a
kind of testing happens when it does not, and a contract test fails on it.

## Consequences

- `pytest -m unit` cannot disagree with the directory layout, and a moved file
  cannot keep a stale label. The two facts have one source.
- 187 existing tests moved. Their history follows them, because `git mv`
  preserves the blob, but every document naming a test file needed updating —
  twenty-six references across nineteen files. That cost is paid once and is far
  smaller now than it would be at Phase 100.
- Numbered ADRs and research ledgers were deliberately **not** updated. They are
  immutable records of what was true at their date, and a stale path in one is
  correct in a way an edited one would not be.
- Test modules are imported under fully-qualified names, so two levels may hold
  a module of the same basename without colliding.
- Contributors must write `from tests.support import ...`. That is a real
  import, resolvable by any tool, rather than a name that happens to be findable.
- A test placed outside a level directory receives no marker and is silently
  omitted from every filtered run. A contract test fails on it by name, because
  the alternative — a collection-time exception — obscures which file caused it.

## Alternatives Considered

**Markers only, keeping the flat directory.** Rejected. It requires a decorator
on every test, which is one opportunity per test to forget, and nothing notices
an omission: the test still runs in a full sweep while disappearing from every
filtered one. It also scales badly — one directory for the suite of a 320-phase
programme.

**Directories without the package, keeping `from conftest import`.** Not
possible. That import depends on which directory pytest places on `sys.path`,
which is exactly what subdirectories change.

**Keeping helpers in `conftest.py` and importing it by path.** Rejected as
building on the same accident. A helper a test imports is a module; naming it
one costs nothing and removes the dependency on pytest's path handling.

**Levels by naming convention rather than directory**, such as
`test_unit_foo.py`. Rejected. It puts every level in one directory, so the tree
stops communicating structure, and it relies on a prefix nothing enforces.

## Risks and Trade-offs

The characteristic failure of a derived marker is that the derivation stops
working and nobody notices, because the full suite still passes and only
filtered runs go quiet. A gate that selects `-m contract` would then check
nothing while reporting success. `tests/contract/test_quality_contract.py`
answers this directly: it asserts that it is itself marked `contract` without
ever declaring so, so the hook breaking makes that test fail.

The second risk is boundary drift. `unit` and `integration` are distinguished by
whether collaborators are substituted, and that judgement is genuinely a
judgement. If integration tests accumulate that use only doubles, the level
stops meaning anything. The signal is `tests/integration/` growing while its
runtime stays flat.

Making `tests` a package also means a module-level import error in any test file
surfaces at collection rather than at execution, so one broken import stops the
whole run. That is the correct trade — a broken import is not a partial success —
but it is a change in behaviour.

## References

- [`../TESTING_STRATEGY.md`](../TESTING_STRATEGY.md) — the levels, how to choose
  between them, fixture scope and naming.
- [`../engineering/REPOSITORY_LAYOUT.md`](../engineering/REPOSITORY_LAYOUT.md) —
  the rule against directories without content.
- [`../research/phase_004_sources.md`](../research/phase_004_sources.md) —
  entries S-01 and S-02 on pytest import modes and marker registration.
- [ADR-0016](0016-phase-004-absorbs-the-quality-gate-scope.md) — the scope
  amendment under which this was delivered.

## Supersedes

None.

## Superseded By

None.
