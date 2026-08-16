# ADR-0055 — The first runtime dependencies are introduced, and GLOBIN becomes an installed application

## Status

Accepted — Phase 021.

**Date:** 2026-08-16

## Context

`project.dependencies` was empty from Phase 001 to Phase 020, and
[ADR-0003](0003-zero-budget-open-source-dependency-policy.md) made that an
invariant rather than a default. `tests/contract/test_packaging_contract.py`
asserted it, `docs/DEPENDENCY_POLICY.md` said that "anything adopted today is a
development dependency by construction", and
[ADR-0054](0054-the-toolchain-is-locked-with-pep-751-and-the-verdict-is-recomputed.md)
built a gate that fails the moment the invariant ends without a lock beside it.

`ROADMAP.md` gives Phase 021 the title *Core Runtime Dependency Introduction* and
the purpose *"Introduce the first runtime dependencies under the zero-budget
policy with explicit justification per package"*. Three questions were deferred
into this phase by name in `docs/engineering/DEPENDENCY_LOCKING.md`: the first
runtime dependency and the `pylock.toml` that must accompany it, whether the
`dev` extra becomes a PEP 735 dependency group, and widening the SBOM from the
declared set to the locked transitive set. `docs/DEPENDENCY_POLICY.md` deferred a
fourth: whether the vulnerability threshold must become severity-aware.

A fifth pressure arrived from the other half of this phase. A console entry point
— `globin` — exists only once something is **installed**, and installing GLOBIN
into `.venv` is what makes `python -m globin` and `globin` two ways into one
program rather than one way and a promise. That install pulls
`project.dependencies`, which is why the two halves of Phase 021 could not be
separated: an entry point needs an install, an install needs the dependencies
resolved, and resolved dependencies need a lock.

## Decision

**`project.dependencies` names `numpy` and `pandas`, each with a written review.**
`docs/engineering/dependency-reviews.toml` carries the six-question review from
`docs/DEPENDENCY_POLICY.md` for both, at `scope = "runtime"`. Neither is imported
by anything yet; Phase 022 installs and verifies them, and this phase makes no
claim about their correctness. The bound in `pyproject.toml` is the version
`docs/engineering/wheel-survey.toml` surveyed, and the exact version lives in the
lock.

**`pylock.toml` accompanies them, and is checked the same way `pylock.dev.toml`
is.** Every claim it makes about itself — a digest in a permitted algorithm,
HTTPS from the declared host, PEP 425 tags that serve the pinned interpreter, no
unowned source-only package — is recomputed by `tools/quality/lock`. A committed
lock nobody validated would make ADR-0054's title true of one file and false of
the other.

**`[runtime] roots` is compared against `project.dependencies` in both
directions**, exactly as `[dev] roots` already is against the `dev` extra. pip
records no dependency edges, so a root removed from the project and left in the
declaration is otherwise undetectable offline.

**`scripts/bootstrap.ps1` installs three things, in order**: the toolchain from
`pylock.dev.toml`, the runtime dependencies from `pylock.toml`, and then GLOBIN
itself with `--no-deps --editable`. The order is what makes `--no-deps` safe:
everything `project.dependencies` names is already present at the locked version,
so pip has nothing left to resolve. Editable, so `globin` and `python -m globin`
read one source tree.

**The project's own distribution is declared, not inferred.**
`docs/engineering/lock-policy.toml` gains a `[project]` table saying that
`globin` is expected to be installed. It is not added to `[environment] seeded`,
which means "the environment created this by itself" — true of `pip` and false of
this.

**The SBOM describes the locked transitive set as well as the declared one.**
`tools/quality/supply/locked.py` reads the committed locks through the one lock
reader. The `dependencies` graph stays narrower than the components array: the
root depends on the direct components and nothing depends on anything else,
because a lock carries no edges.

**PEP 735 is not adopted.** `docs/engineering/DEPENDENCY_LOCKING.md` measured
that a lock produced through a dependency group is byte-identical to one produced
from a requirements file, and said the argument for it becomes visible when
something is published. GLOBIN carries `Private :: Do Not Upload` and publishes
nothing, so the argument has not become visible; the `dev` extra stays an extra.

**The vulnerability threshold stays blunt.** Any open finding fails the gate at
any severity, and `docs/engineering/vulnerability-waivers.toml` is the pressure
valve — a finding that cannot be fixed today is waived by name, with a reason and
an owner. A severity threshold is a standing decision to ignore a class of
finding nobody has looked at; a waiver is a diff somebody reviewed.

**Out of scope.** Which libraries later bands adopt, whether they work, and any
claim about numerical correctness. Phase 022 installs and verifies the scientific
stack; this phase declares, reviews and locks it.

## Consequences

The zero-dependency era is over, and the cost is real: the audited set grows, a
clean checkout now downloads two large wheels and their transitive closure, and
`bootstrap.ps1` takes materially longer than it did.

`tests/contract/test_packaging_contract.py` no longer asserts the list is empty.
That was deliberate friction and spending it bought something stronger: the
declared set and the reviewed set are now compared in both directions, so a
dependency added without a review fails, and so does a review left behind for
something no longer declared.

Two distributions are declared that nothing imports. A reader encountering that
will reasonably ask why, and the answer is only in the review records and here —
which is the cost of separating "may we depend on this" from "does it work".

Adding a runtime dependency now costs a review, a relock, and a commit that
carries both. Removing one costs the same in reverse, and the declaration will
name what was left behind.

`docs/DEPENDENCY_POLICY.md` gained `0BSD`, `Zlib` and `CC0-1.0` and a rule for
compound SPDX expressions, because the first runtime dependency publishes an
expression rather than an identifier. That table had never been extended before.

## Alternatives Considered

**Introduce nothing, and deliver only the machinery.** The lock pairing, the
PEP 735 decision and the SBOM widening could each have been settled without a
package. Rejected because `pip-audit --locked` raises on a lock recording no
packages, so `pylock.toml` cannot exist as an empty file — the mechanism cannot
be demonstrated without something to lock, and a mechanism nobody has run is a
mechanism nobody has tested.

**Introduce one package rather than two.** `numpy` alone would have proven the
lock pairing at a smaller blast radius. Rejected because `pandas` requires
`numpy` anyway: locking one and not the other would produce a lock that the very
next phase invalidates, and two relocks where one was needed.

**Install GLOBIN non-editable.** Simpler, and closer to what a user would get.
Rejected because the console script would then answer about a copy taken at
install time, so a developer changing a file would be told about the version they
no longer have — and `globin doctor` exists precisely to be trusted about the
tree in front of you.

**Add `globin` to `[environment] seeded`.** One line instead of a table.
Rejected because `seeded` means the environment created it, and writing something
false into a declaration to save four lines is how a declaration stops being
readable.

**Make the vulnerability threshold severity-aware now.** The paragraph in
`docs/DEPENDENCY_POLICY.md` predicted this would be needed. Rejected on the
evidence rather than the prediction: the blunt rule's cost is one waiver per
finding, and no findings have arrived yet. Phase 032 is named as where to
revisit it with numbers.

## Risks and Trade-offs

**The characteristic failure mode is a lock that drifts from the environment
without anybody noticing**, because `lock installed` is the only check that can
see it and it reports `unmeasured` unless run through `.venv`'s own interpreter.
The observable signal is a CI `runtime` job that passes while a developer's
`globin doctor` reports a missing dependency.

**The second is a review that becomes untrue.** A licence read on 2026-08-16 is
a fact about that day, and `numpy`'s compound expression in particular is the
kind that changes when a vendored component is replaced. Nothing re-reads it;
`python -m tools.quality supply` audits vulnerabilities and not licences. The
signal is a `pip-audit` finding whose advisory mentions a relicensing, and there
is no automated one.

**The third is that two declared, unimported packages invite a third.** The
review process is the only thing standing between "Phase 022 will need it" and a
manifest nobody reviewed. The signal is a review record whose reason is a phase
number and nothing else.

Confidence is high on the mechanism and moderate on the package choice: `numpy`
and `pandas` are named by `wheel-survey.toml` against Phase 022, which is a
schedule rather than a completed design.

## References

- [ADR-0003](0003-zero-budget-open-source-dependency-policy.md) — the invariant this ends
- [ADR-0044](0044-dependency-review-is-a-written-process-with-a-generated-inventory.md) — the review process
- [ADR-0054](0054-the-toolchain-is-locked-with-pep-751-and-the-verdict-is-recomputed.md) — the lock gate this extends
- [ADR-0056](0056-phase-021-widens-to-deliver-the-application-bootstrap.md) — the other half of this phase
- [`../DEPENDENCY_POLICY.md`](../DEPENDENCY_POLICY.md) — the six questions and the licence table
- [`../engineering/DEPENDENCY_LOCKING.md`](../engineering/DEPENDENCY_LOCKING.md) — the deferrals this discharges
- [`../engineering/wheel-survey.toml`](../engineering/wheel-survey.toml) — the surveyed versions
- [`../research/phase_021_sources.md`](../research/phase_021_sources.md) — the licence and metadata reads

## Supersedes

None.

## Superseded By

None.
