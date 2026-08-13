# Architecture Decision Records

An ADR records a decision with lasting consequence: what was decided, the
context that made it necessary, and what it costs. The context matters as much
as the decision. A future contributor who understands only *what* was chosen
will eventually undo it; one who understands *why* can tell whether the reason
still applies.

## Rules

1. **Numbering is contiguous from `0001` and never reused.** Filenames follow
   `NNNN-kebab-case-title.md`.
2. **Accepted ADRs are immutable.** A changed decision is written as a *new*
   ADR that supersedes the old one. The superseded record stays, with its status
   updated, so the reasoning history survives.
3. **Every ADR has four sections**, in this order: `## Status`, `## Context`,
   `## Decision`, `## Consequences`. This is checked by
   `tests/test_documentation_contract.py`.
4. **Every ADR is listed in this index.** Also checked by test.
5. Status is one of: `Proposed`, `Accepted`, `Superseded by ADR-NNNN`,
   `Deprecated`.

## When to write one

Write an ADR when a choice constrains future work, is expensive to reverse, or
would otherwise be re-litigated by someone who does not know why it was made.
Do not write one for routine implementation detail — that belongs in code and
its docstrings.

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

## Relationship to other documents

ADRs record *decisions*. Durable technical reasoning that is not a single
decision belongs in [`../ARCHITECTURE_PRINCIPLES.md`](../ARCHITECTURE_PRINCIPLES.md).
Evidence supporting a decision belongs in [`../research/`](../research/), cited
from the ADR rather than restated inside it.
