# ADR-0036 — Test execution is sharded by a stable digest, not by a plugin

## Status

Accepted — Phase 009.

**Date:** 2026-08-14

## Context

The brief supplied for this phase asked for parallel test execution, flakiness
detection, deterministic sharding and duration budgets. `ROADMAP.md` assigns
Phase 009 to *Time, Clock and Timezone Discipline*, so the request arrived as
tooling rather than as phase scope — the seventh time a brief has collided this
way, and the situation
[ADR-0032](0032-verification-tooling-may-be-added-outside-phase-scope.md) exists
to govern.

Its third condition is that the addition **adds no dependency**, and
`pytest-xdist` is one. ADR-0032 is explicit about where that leads: "anything
that arrives as a dependency needs Phase 014's review process, which does not
exist yet". There is no reading of the six conditions under which the obvious
implementation is permitted.

Two independent facts made the refusal easier rather than harder. PyPI shows
`pytest-xdist` 3.8.0 declaring support through Python 3.13 and `execnet` 2.1.2
through 3.12; this repository runs **Python 3.14.5 with pytest 9.0.3**, so
neither claims the interpreter in use. And
[ADR-0023](0023-property-based-testing-as-a-sixth-taxonomy-level.md) already
rejected `pytest-randomly` and `pytest-socket` as "scope creep with a cost that
compounds", preferring "fifteen lines of standard library". The dependency-free
route is this repository's own precedent, not a compromise reached for lack of
one.

The owner was given four options with the conflict named and chose the roadmap's
phase in full plus the dependency-free part of the brief, on the ADR-0032
pattern.

## Decision

**1. A run is identified by a manifest and a digest.** Collection output is
parsed into node IDs, sorted, and hashed with `sha256` over a payload carrying a
domain tag, the schema version, the selection expression, the count and the IDs.
Everything machine-specific — platform, versions, timings — lives under `meta`
and is never hashed, because a digest that moved between machines could not
answer the only question it is for.

**2. The parser checks itself against pytest's own count.** pytest prints how
many tests it collected, so the manifest is refused rather than written when the
two disagree. This is not defensive decoration: it is what caught the first
implementation dropping four real tests whose parametrised IDs contain
backslashes, and without it that manifest would have shipped.

**3. Node IDs are validated asymmetrically.** A backslash in the *path* is
refused, because pytest emits forward slashes even on Windows and a backslash
there means the platform started writing paths its own way — a difference that
must surface rather than be normalised into a digest. A backslash *after* `::`
is permitted, because pytest escapes special characters inside a parametrised
ID: a fixture string containing a newline appears as a literal `\n`, and `ç` as
`\xe7`.

**4. The partition is a seeded digest-sort dealt round robin.** Python's builtin
`hash()` is forbidden and appears nowhere — hash randomisation makes it differ
between processes, so a partition built on it would be stable within one run and
meaningless between two. The mapping is exactly balanced for every seed, is
independent of input order, and varies the order *within* a shard, which is what
lets a future soak find an order-dependent test with no plugin.

**5. Shards run sequentially, and `--concurrent` is deliberately not offered.**
A gate whose verdict can depend on OS scheduling is what this repository
refuses. What sequential execution establishes is isolation — that no test
depends on sharing a process with another — not concurrency safety, and offering
a flag would invite people to believe otherwise.

**6. Every child gets its own `COVERAGE_FILE`, and `[tool.coverage.*]` is not
touched.** `parallel`, `relative_files` and a `[paths]` section are all read by
the *existing* `coverage` and `full` gates, so adding them would change what
those gates do — ADR-0032 condition 5 forbids exactly that. The consequence is
stated rather than hidden: **combining is same-machine only.**

**7. Every child passes `--cov-fail-under=0`.** `pytest-cov` reads `fail_under`
from `[tool.coverage.report]` when nothing overrides it, and this repository sets
it to 95. A shard measures a fraction of the suite — measured here, one quarter
reaches 87.43% — so without the flag every shard exits 1 and the gate reports a
broken suite while nothing is broken.

**8. Four exit states, never two**: passed, failed, usage, and *ran but measured
nothing*. Only pytest's `0` and `1` are verdicts about tests. `5` is the trap
that makes a shard silently vacuous; `4` is what pytest returns for a node ID
that no longer exists, which is collection drift observed rather than inferred.
An unmeasured shard **outranks** a failed one, because the partition not
describing what ran casts doubt on the shards that passed.

## Consequences

`python -m tools.quality shards` exists, and it is **slower** than `coverage`,
not faster. It buys evidence, not time. The command table row says so, because
somebody will otherwise reach for it expecting a speed-up.

The suite gained three test modules and the repository a `.globin/` directory,
ignored before the first byte was written.

What is genuinely **not** delivered, and has no dependency-free substitute:
concurrent workers and therefore any race between them; `xdist`'s `worker_id`
and its worker-scoped fixture semantics; dynamic work stealing; and crash
attribution finer than "this shard". Each is recorded in `QUALITY_GATES.md`'s
deferral register against Phase 014, so the absence is a decision with an owner
rather than a gap.

## Alternatives Considered

**Adopt `pytest-xdist`.** The obvious implementation, and it would deliver the
concurrency this cannot. Refused under ADR-0032 condition 3, which is absolute
and which ADR-0032 itself names as the condition that "rules out most tools
worth wanting". Revisit after Phase 014 builds the review process — and note
then that neither `pytest-xdist` nor `execnet` currently declares support for
this interpreter.

**Write an ADR extending ADR-0032 to permit this one dependency.** ADR-0032
anticipates precisely this: "the observable signal is an ADR citing this one
while arguing that one condition is unnecessary in its particular case. That
argument is the thing this record exists to make visible, and it should be
answered by refusing rather than by extending."

**Contiguous slices of the sorted list.** Perfectly balanced and free, and it
keeps each module intact in one shard — the `loadfile` property. Rejected
because that same property makes the partition useless as an order probe: within
a module the order never varies, whatever the seed.

**Digest modulo the shard count.** Deterministic and seed-varying, but its
balance is only statistical and on a small selection it can leave a shard empty
— which is pytest exit 5, the trap decision 8 exists to catch.

**Emulate `loadfile`/`loadscope` by dealing groups instead of tests.** Buildable
with the same algorithm. Rejected because it would weaken the order-independence
probe for no benefit this repository can currently use, and it would cost the
exact balance guarantee.

**Add `parallel = true` to the coverage configuration.** The documented way to
collect from many processes. Rejected under ADR-0032 condition 5: it changes
where the *existing* gates write.

## Risks and Trade-offs

**The characteristic failure is believing this tests concurrency.** It does not.
A reader who sees "multi-process" and concludes that races are covered will be
wrong in exactly the situation where being wrong is expensive. The observable
signal is somebody citing this gate as evidence that a shared-state bug cannot
exist. Both this record and the command table row say sequential explicitly.

**The manifest can go stale between generation and use.** It is regenerated at
the start of every run, so the window is one run — but a tree edited *during* a
run produces exit 4 or 5 rather than a wrong answer, which is why both are
unmeasured and why both print what to do.

**Same-machine combining is a real limit**, and it will be felt the first time
somebody wants to combine a Windows run with a Linux one. The fix is
`relative_files` and a `[paths]` section, which is a coverage-configuration
change and therefore a change to the existing gates — a separate decision, taken
deliberately, not smuggled in here.

**The `.globin/` directory is one more thing that can be left behind.** It is
pruned at the start of each run and ignored by Git, but a stale manifest read by
a person rather than by the tool would mislead.

## References

- [ADR-0032](0032-verification-tooling-may-be-added-outside-phase-scope.md) — the six conditions this satisfies
- [ADR-0033](0033-mutation-testing-is-a-repository-native-ast-harness.md) — the harness whose shape this follows
- [ADR-0023](0023-property-based-testing-as-a-sixth-taxonomy-level.md) — the earlier refusal of test plugins
- [ADR-0019](0019-single-quality-entrypoint.md) — one command table, three consumers
- [`../engineering/QUALITY_GATES.md`](../engineering/QUALITY_GATES.md) — the command row and the deferral register
- [`../TESTING_STRATEGY.md`](../TESTING_STRATEGY.md) — flaky tests are diagnosed, never retried
- [`../research/phase_009_sources.md`](../research/phase_009_sources.md)
- [`../../ROADMAP.md`](../../ROADMAP.md) — Phase 014, which owns dependency review

## Supersedes

None.

## Superseded By

None.
