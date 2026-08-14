# ADR-0023 — Property-based testing is a sixth taxonomy level, with two Hypothesis profiles

## Status

Accepted — Phase 005.

**Date:** 2026-08-14

## Context

[ADR-0017](0017-test-taxonomy-as-directories.md) established five test levels,
one directory each, with the level derived from the directory by a collection
hook. That decision is unchanged by this record and remains Accepted; what
changes is the number of levels.

The repository has accumulated code whose correctness is a statement about *every*
input rather than about a few: `band_for_phase` must be total over 1..320,
`import_cycles` must produce the same answer whatever order modules arrive in,
`top_level_package` must be idempotent, `module_name` must map two different
path shapes onto one name.
[`ENGINEERING_CONTRACT.md`](../engineering/ENGINEERING_CONTRACT.md) invariant 3
has required order-independence since Phase 001, and nothing asserted it — the
single production call site scans in sorted order, so the invariant could have
been false for four phases without any test noticing.

Example-based tests cannot close that gap, because an example-based test only
asserts what its author thought of. That is not a hypothetical objection: the
first run of the new property tests produced two failures that were both defects
in the *tests*, one asserting that a module name never contains `.py` (a module
legitimately called `py` is `globin.py`) and one generating `import as`. Both are
exactly the inputs a human writing examples does not picture.

## Decision

**1. `property` is a sixth taxonomy level**, with a directory at
`tests/property/` and a registered marker, applied automatically by the same
hook as the other five. ADR-0017's mechanism is reused unchanged; only
`TAXONOMY_LEVELS` grows. A level with no tests still fails the contract suite,
so the directory cannot become a placeholder.

**2. Hypothesis is the tool**, added to the `dev` optional-dependency group.
It is MPL-2.0 and its only runtime requirement is `sortedcontainers`
(Apache-2.0), so ADR-0003 permits it as development tooling; the runtime
dependency list stays empty and a contract test still asserts that. The exact
version is pinned in CI alongside the other five tools.

**3. Two profiles, registered in `tests/conftest.py`:**

- `dev` — the exploratory loop. Keeps the example database, so a failure found
  once replays first on the next run.
- `ci` — `derandomize=True` and `database=None`. The same code examines the same
  inputs on every run, and nothing is carried between runs.

**4. The gate uses the `ci` profile locally as well as in CI.** `python -m
tools.quality full` passes `--hypothesis-profile=ci`. A gate that searched a
different input space on each machine could pass on the machine that wrote the
code and fail on the one that reviewed it, for no visible reason, which is the
class of failure the single command table exists to prevent. The exploratory
profile is reached through the separate `property` command.

**5. `deadline=None` in both profiles.** Hypothesis's default 200 ms per-example
deadline is a timing assertion, `filterwarnings = ["error"]` turns its complaint
into a hard failure, and CI runs on a shared Windows runner. Keeping it would
have produced a test that fails for reasons unrelated to the property.
`max_examples` is what bounds the work.

**6. `print_blob=True` in both**, so a failure prints a `@reproduce_failure`
decorator. That, rather than a pinned seed, is the documented way to reproduce
one: pinning a seed to make a failure reproducible would also stop the search
that found it.

**7. A property test is written when an invariant exists, not by default.**
[`DEFINITION_OF_DONE.md`](../engineering/DEFINITION_OF_DONE.md) says so
explicitly. Requiring one per change would produce slow tests that assert very
little and would devalue the level.

**8. Stateful testing is not adopted.** Hypothesis's rule-based state machines
suit an object with a lifecycle, and GLOBIN has none — order lifecycle is Phases
081-096. Nothing here prevents adopting it then; a synthetic state machine
invented now to justify the feature would have to be deleted first.

## Consequences

- The toolchain has six entries rather than five, and
  `test_development_extra_is_a_free_toolchain` had to be edited to say so. That
  edit is the review.
- Two documented invariants are now checked that never were: the review's
  order-independence, and the canonical rotation of a discovered cycle.
- Property tests are slower than the rest of the suite by roughly an order of
  magnitude per test. At 200 examples the whole suite still runs in under nine
  seconds, so no deselection is warranted yet; the `slow` marker exists if that
  changes.
- `.hypothesis/` appears in the working tree under the `dev` profile.
  `.gitignore` has covered it since Phase 001, which was written before anything
  produced it.
- A contributor who runs `pytest` directly gets the `dev` profile, while the gate
  uses `ci`. A property that fails only under one of them is possible and would
  be confusing; it is also information, because it means the property depends on
  which examples were drawn.

## Alternatives Considered

**Put property tests inside the existing levels**, marking them by hand rather
than adding a directory. Rejected because it contradicts ADR-0017's central
decision — that a test's directory decides its level and no test declares its own
— and would reintroduce exactly the drift that decision removed.

**Use one Hypothesis profile.** Rejected in both directions. A single
`derandomize` profile makes local exploration pointless, since every run examines
the same inputs and a passing test stays passing. A single non-derandomised
profile makes CI failures that may not reproduce, which trains people to press
retry.

**Select the profile from an environment variable**, the common convention.
Rejected. It puts the gate's behaviour in machine configuration rather than in
the command table, which is the arrangement ADR-0019 exists to prevent; a machine
with the variable unset would silently run a different gate.

**Write generators by hand instead of adding a dependency.** Rejected. The
shrinking is the point: an unshrunk counter-example from a hand-rolled generator
is a wall of random data, and the value of both real failures found on the first
run came from Hypothesis reducing them to `parts=['py']` and `imported=['as']`.

**Adopt `pytest-socket`, `pytest-randomly` and similar alongside it.** Rejected
as scope creep with a cost that compounds; the offline guard
([ADR-0024](0024-tests-are-offline-and-isolated-by-construction.md)) is fifteen
lines of standard library and needs no dependency.

## Risks and Trade-offs

The characteristic failure mode is property tests that restate the
implementation. A property asserting that `top_level_package` returns
`module.split(".")[0]` would pass forever and catch nothing, and it is an easy
thing to write when a genuine invariant is not obvious. The observable signal is
a property test that would have to change if the implementation were rewritten
correctly — such a test is coupled to the algorithm, not to the contract.

A second risk is the level becoming a dumping ground for slow example-based
tests that happen to use `@given` over a two-element strategy. `tests/property/`
has a docstring saying what belongs there; nothing enforces it, and nothing
easily could.

Finally, `derandomize=True` means CI examines a fixed input set derived from the
test's own name, so CI will not find a new counter-example on a rerun of
unchanged code. That is the trade made for reproducibility, and it is why the
`dev` profile keeps searching: the exploration happens locally, and the gate
confirms.

## References

- [ADR-0017](0017-test-taxonomy-as-directories.md) — the level-by-directory
  mechanism this record extends rather than replaces.
- [ADR-0003](0003-zero-budget-open-source-dependency-policy.md) — the tooling
  exemption that permits a sixth development dependency.
- [ADR-0019](0019-single-quality-entrypoint.md) — why the profile is selected in
  the command table rather than by the environment.
- [`../TESTING_STRATEGY.md`](../TESTING_STRATEGY.md) — the level's definition and
  the failure-reproduction procedure.
- [`../research/phase_005_sources.md`](../research/phase_005_sources.md) —
  entries covering Hypothesis settings, profiles and the pytest plugin.

## Supersedes

None. The record establishing level-by-directory remains Accepted and is
extended rather than replaced — its mechanism is what this record relies on, and
only the number of levels changes.

## Superseded By

None.
