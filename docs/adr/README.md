# Architecture Decision Records

An ADR records a decision with lasting consequence: what was decided, the
context that made it necessary, and what it costs. The context matters as much
as the decision. A future contributor who understands only *what* was chosen
will eventually undo it; one who understands *why* can tell whether the reason
still applies.

## Rules

1. **Numbering is contiguous from `0001` and never reused.** Filenames follow
   `NNNN-kebab-case-title.md`. Start from [`TEMPLATE.md`](TEMPLATE.md).
2. **Accepted ADRs are immutable.** A changed decision is written as a *new*
   ADR that supersedes the old one. The superseded record stays, with its status
   updated, so the reasoning history survives.
3. **Every ADR has four sections**, in this order: `## Status`, `## Context`,
   `## Decision`, `## Consequences`. This is checked by
   `tests/contract/test_documentation_contract.py`. Records from 0012 onwards additionally
   carry `## Alternatives Considered`, `## Risks and Trade-offs`,
   `## References`, `## Supersedes` and `## Superseded By`, and that is checked
   too. Earlier records predate those sections and are immutable, so they are
   not retrofitted — see [`TEMPLATE.md`](TEMPLATE.md).
4. **Every ADR is listed in this index**, with the same status the record itself
   states. Both are checked by test.
5. Status is one of: `Proposed`, `Accepted`, `Rejected`, `Deprecated`, or
   `Superseded by ADR-NNNN`.

## When to write one

Write an ADR when a choice constrains future work, is expensive to reverse, or
would otherwise be re-litigated by someone who does not know why it was made.
Do not write one for routine implementation detail — that belongs in code and
its docstrings.

The categories that reliably qualify are structure, non-functional requirements,
dependencies between components, published interfaces, and construction
techniques such as a library or tool the project commits to. See
[`../research/phase_003_sources.md`](../research/phase_003_sources.md) entries
S-04 and S-05.

## Changing a decision

A record is immutable once it is `Accepted` **or** `Rejected`. A rejected record
is kept rather than deleted: it records that the question was asked and
answered, which is what stops the same debate recurring a year later.

To change a decision:

1. Write a **new** ADR with the next contiguous number.
2. Name the record it replaces under its `## Supersedes` heading.
3. In the same commit, set the old record's `## Status` to
   `Superseded by ADR-NNNN` and fill in its `## Superseded By` heading. That
   status edit is the only change an immutable record accepts.
4. Update the status column for both records in the index below.

Doing this in one commit is not tidiness. A test asserts that the two records
point at each other and that the index agrees with both, so a half-finished
supersession fails the build rather than leaving the log quietly inconsistent.

Never edit the reasoning of an accepted record to match a newer view. The value
of the log is that it shows what was believed at the time, which is the only way
a future reader can judge whether the reason still holds.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-project-identity-and-python-first-local-architecture.md) | Project identity and Python-first local architecture | Accepted |
| [0002](0002-binance-global-only-exchange-scope.md) | Binance Global is the only venue in scope | Accepted |
| [0003](0003-zero-budget-open-source-dependency-policy.md) | Zero-budget runtime and open-source dependency policy | Accepted |
| [0004](0004-official-apis-only-no-scraping.md) | Official documented interfaces only; no scraping | Accepted |
| [0005](0005-master-only-git-workflow.md) | Master-only Git workflow | Accepted |
| [0006](0006-product-and-environment-capability-matrix.md) | Binance integration is driven by a product and environment capability matrix | Accepted |
| [0007](0007-autonomous-learning-governance.md) | Autonomous learning is governed by evidence gates | Accepted |
| [0008](0008-immutable-upper-risk-constraints.md) | Upper risk bounds are immutable and outside the search space | Accepted |
| [0009](0009-windows-bat-launchers-as-entry-points.md) | Two Windows BAT launchers are the final user entry points | Accepted |
| [0010](0010-living-documentation-responsibilities.md) | Documentation is a deliverable, kept live by tests | Accepted |
| [0011](0011-documentation-authority-hierarchy.md) | Documentation has an explicit authority order, with code at the top | Accepted |
| [0012](0012-phase-003-delivers-architecture-boundaries.md) | Phase 003 delivers architecture boundaries; static analysis moves to Phase 013 | Accepted |
| [0013](0013-modular-monolith-as-the-initial-architecture.md) | GLOBIN is a modular monolith in a single Python distribution | Accepted |
| [0014](0014-layered-ports-and-adapters-and-inward-dependencies.md) | Five layers with dependencies pointing inward, enforced by a machine-readable contract | Accepted |
| [0015](0015-single-composition-root-and-no-import-time-side-effects.md) | Dependencies are wired in one composition root, and importing performs no work | Accepted |
| [0016](0016-phase-004-absorbs-the-quality-gate-scope.md) | Phase 004 absorbs the quality-gate scope from Phase 013 | Accepted |
| [0017](0017-test-taxonomy-as-directories.md) | Test level is decided by directory, and `tests` is a package | Accepted |
| [0018](0018-quality-toolchain-and-explicit-strictness.md) | The quality toolchain is pinned, and strictness is written out flag by flag | Accepted |
| [0019](0019-single-quality-entrypoint.md) | One command table defines the checks, and every caller reads it | Accepted |
| [0020](0020-verification-only-continuous-integration.md) | Continuous integration verifies, with least privilege and pinned actions | Accepted |
| [0021](0021-phase-005-widens-to-include-the-test-foundation.md) | Phase 005 widens to deliver the error taxonomy and the deterministic test foundation | Accepted |
| [0022](0022-error-taxonomy-rooted-in-one-type.md) | One error root, five categories chosen by who must act, and no builtin inheritance | Accepted |
| [0023](0023-property-based-testing-as-a-sixth-taxonomy-level.md) | Property-based testing is a sixth taxonomy level, with two Hypothesis profiles | Accepted |
| [0024](0024-tests-are-offline-and-isolated-by-construction.md) | Tests are offline and process-isolated by construction, not by convention | Accepted |
| [0025](0025-structured-logging-is-a-redacted-domain-event.md) | A log record is a domain event that redacts itself, emitted through a port | Accepted |
| [0026](0026-correlation-is-bound-explicitly-not-ambiently.md) | Correlation is bound explicitly, and the timestamp belongs to the adapter | Accepted |
| [0027](0027-configuration-is-a-frozen-dataclass-validated-at-the-boundary.md) | Configuration is a frozen dataclass validated at one boundary, and the dataclass is the schema | Accepted |
| [0028](0028-configuration-layers-override-last-wins-and-carry-their-origin.md) | Configuration layers are flat, override last-wins, carry their origin, and cannot remove a setting | Accepted |
| [0029](0029-a-severity-threshold-is-a-decorating-sink.md) | A severity threshold is a decorating sink, not a field on a sink or a check in the logger | Accepted |
| [0030](0030-domain-values-are-denominated-wrappers-over-decimal.md) | Domain values are denominated frozen wrappers over `Decimal`, never subclasses of it | Accepted |
| [0031](0031-value-types-compare-but-do-not-compute.md) | Value types compare but do not compute; a wrong type returns `NotImplemented` and a wrong unit raises | Accepted |
| [0032](0032-verification-tooling-may-be-added-outside-phase-scope.md) | Verification tooling may be added outside phase scope, under six conditions | Accepted |
| [0033](0033-mutation-testing-is-a-repository-native-ast-harness.md) | Mutation testing is a repository-native `ast` harness gated by a committed survivor set | Accepted |
| [0034](0034-time-is-injected-and-internal-time-is-utc.md) | Time is an injected clock behind two ports, and internal time is UTC | Accepted |
| [0035](0035-milliseconds-are-a-floored-projection.md) | Milliseconds are a floored projection, not the representation | Accepted |
| [0036](0036-test-execution-is-sharded-by-a-stable-digest-not-by-a-plugin.md) | Test execution is sharded by a stable digest, not by a plugin | Accepted |

## Relationship to other documents

ADRs record *decisions*. Durable technical reasoning that is not a single
decision belongs in [`../ARCHITECTURE_PRINCIPLES.md`](../ARCHITECTURE_PRINCIPLES.md).
Rules about how work is carried out belong in
[`../engineering/`](../engineering/ENGINEERING_CONTRACT.md). Evidence supporting
a decision belongs in [`../research/`](../research/), cited from the ADR rather
than restated inside it.

Where an ADR and another document appear to disagree, the precedence order in
[`../engineering/SOURCE_OF_TRUTH.md`](../engineering/SOURCE_OF_TRUTH.md) applies.
