# ADR-0014 — Five layers with dependencies pointing inward, enforced by a machine-readable contract

## Status

Accepted — Phase 003.

**Date:** 2026-08-14

## Context

[`../engineering/ENGINEERING_CONTRACT.md`](../engineering/ENGINEERING_CONTRACT.md)
already requires that the domain be separated from adapters (invariant 7) and
that dependencies point inward (invariant 19). Both were stated in prose and
neither was enforceable, because the repository did not say what the layers
*are*. An invariant with no named subject cannot be checked, and
[`../ARCHITECTURE_PRINCIPLES.md`](../ARCHITECTURE_PRINCIPLES.md) principle 10 is
explicit that a policy existing only in prose erodes.

The specific erosion to prevent is well understood in this domain. GLOBIN's core
concepts — instruments, orders, positions, exposure, signals — are the same
whether the venue is reached over REST, over WebSocket, over FIX, or not at all.
If those concepts learn about Binance, three things follow: the core can no
longer be tested without a network, a change to a Binance endpoint reaches into
risk logic, and the system cannot be exercised against recorded data. The last
of those matters most, because ADR-0006 establishes that Binance's test
environments do not cover every product; being able to run the core against
fakes is not a convenience but the only way some paths get exercised at all.

The counter-pressure is that layering imposed without enforcement is worse than
no layering, because it creates a claim the codebase does not honour.

## Decision

**1. GLOBIN has exactly five layers**, innermost first:

| Layer | Owns |
|---|---|
| `domain` | Pure concepts, values and rules. Knows nothing outside itself. |
| `ports` | Abstract contracts describing what the core needs from the world. |
| `application` | Use cases coordinating domain objects through ports. |
| `adapters` | Concrete implementations of ports. The only layer that touches the world. |
| `runtime` | The composition root. Builds objects and wires dependencies. |

**2. Dependencies point inward only.** Each layer may import the layers inside
it and nothing outside it. `domain` imports no layer at all. `ports` may not
know who implements it. `application` may not name a concrete adapter.

**3. `domain`, `ports` and `application` perform no I/O.** Importing a module
that can reach the filesystem, the network, the environment, another process or
another thread is the observable form of that rule, and it is what the tests
check. This is a proxy rather than a proof — a layer handed an open socket would
pass — but it catches the way the boundary is realistically crossed.

**4. The matrix lives in exactly one machine-readable file**,
[`../architecture/dependency-rules.toml`](../architecture/dependency-rules.toml).
Prose describes it and tests enforce it; neither restates it. The one sanctioned
copy is the `Layer` enumeration in
[`../../src/globin/domain/architecture.py`](../../src/globin/domain/architecture.py),
and a test compares the two so they cannot diverge — the tripwire pattern from
[`../engineering/SOURCE_OF_TRUTH.md`](../engineering/SOURCE_OF_TRUTH.md).

**5. Ports are `typing.Protocol` classes.** Structural subtyping means an
adapter satisfies a port without importing it, so the dependency points inward
even in the file that implements it, and a test can substitute a fake with no
inheritance ceremony.

**6. Two modules sit above the layer stack.**
[`../../src/globin/project_contract.py`](../../src/globin/project_contract.py)
and [`../../src/globin/roadmap.py`](../../src/globin/roadmap.py) hold identity
and programme policy as constants. Any layer may read them; they may import no
layer. They were not moved into `domain`, because their paths are named directly
by the engineering contracts and the churn would have bought nothing.

Sub-packages inside a layer appear when a phase puts real content in them.
There is no empty `adapters/exchange/` waiting, because
[`../engineering/REPOSITORY_LAYOUT.md`](../engineering/REPOSITORY_LAYOUT.md)
prohibits scaffolding directories in advance.

## Consequences

- Reaching the exchange from a use case now requires defining a port and an
  adapter rather than importing a client. That is more files for the first
  caller and fewer decisions for every caller after it.
- The core becomes testable without a network, a clock or credentials, which is
  the precondition for ADR-0006's capability matrix being exercisable at all.
- Violations fail the build with a message naming the broken rule, so the cost
  of the boundary is paid at the moment it is crossed rather than during a later
  consolidation phase.
- Amending the architecture is now a deliberate act: editing one TOML file,
  which shows up in a diff as a rule change rather than as an import.
- The contract is enforced by GLOBIN's own code —
  `globin.application.architecture_review` wired by
  `globin.runtime.composition`. That code is the phase's worked example of the
  layering as well as its enforcement, so the layers are exercised rather than
  merely declared.
- A real cost: that review only runs from a source checkout, because it needs a
  repository path. It is a development-time capability living in the package
  rather than in `scripts/`, which is a defensible but not obviously correct
  placement. It sits there because Phase 001 set the precedent with
  `project_contract.py` — policy encoded as importable code, asserted by tests —
  and because empty layer packages would have left every boundary test vacuous.
- The I/O rule is expressed as a list of standard library packages. That list
  will need extending as the system grows, and an unlisted I/O route would pass
  unnoticed. It is a tripwire, not a sandbox.

## Alternatives Considered

**Keep the rule in prose and rely on review.** Rejected. GLOBIN has no reviewer:
work happens on `master` with no pull request (ADR-0005), and most contributors
are agents with no memory of previous sessions. A rule enforced by review is a
rule enforced by nobody.

**Adopt an off-the-shelf import linter.** Rejected on the zero-budget dependency
rule (ADR-0003) rather than on quality. `import-linter` solves this problem
well, but the runtime dependency list being empty is an asserted invariant, the
development extra is pinned to exactly four tools by a contract test, and the
standard library's `ast` and `tomllib` cover the requirement in about two
hundred lines. Revisit if the checks outgrow that.

**Three layers — domain, application, infrastructure.** Rejected, but narrowly;
it is the simpler and more common shape. Separating `ports` from `adapters`
earns its place because the interface is what later phases will substitute
against, and burying it inside the implementing layer makes "what does the core
actually require?" a question you answer by reading adapters. Separating
`runtime` from `adapters` earns its place because composition is the one
concern that legitimately sees everything.

**Enforce boundaries with runtime import hooks.** Rejected. A hook fires only on
code paths that execute, so coverage of the rule would depend on test coverage
of the code. Static analysis sees every import in the tree, including ones
inside functions and inside `if TYPE_CHECKING:` blocks.

**Let `domain` import `pathlib` for convenience.** Rejected. It is the first
step of exactly the erosion this record exists to prevent, and the convenience
is available one layer out.

## Risks and Trade-offs

The rule is enforced by a proxy. Import analysis detects capability, not
behaviour: a `domain` function handed an already-open file object performs I/O
while importing nothing suspicious. Anyone reading a green build as proof of
purity is reading it wrong.

The second risk is ceremony. Five layers is more structure than a
three-module package needs, and there is a real chance that early phases spend
effort on indirection that a simpler shape would not have required. The
judgement is that the cost is front-loaded and small while the benefit
accumulates over 317 remaining phases — but it is a judgement, and the signal
that it was wrong would be ports being defined with exactly one implementation
that no test ever substitutes.

Third, the layer set itself is a guess about a system that does not exist yet. A
sixth layer may prove necessary. Adding one is deliberately visible: it requires
editing the contract file *and* the enumeration, and a test fails until both
agree.

## References

- [`../architecture/README.md`](../architecture/README.md) — the layers in prose.
- [`../architecture/dependency-rules.toml`](../architecture/dependency-rules.toml)
  — the canonical matrix.
- [`../engineering/ENGINEERING_CONTRACT.md`](../engineering/ENGINEERING_CONTRACT.md)
  — invariants 7 and 19, which this record makes enforceable.
- [`../research/phase_003_sources.md`](../research/phase_003_sources.md) — S-05
  on `typing.Protocol`, S-06 on `ast`, S-07 on `tomllib`.
- [`0013-modular-monolith-as-the-initial-architecture.md`](0013-modular-monolith-as-the-initial-architecture.md)
  — the topology these boundaries make survivable.

## Supersedes

None.

## Superseded By

None.
