# ADR-0013 — GLOBIN is a modular monolith in a single Python distribution

## Status

Accepted — Phase 003.

**Date:** 2026-08-14

## Context

The programme will eventually produce a system with market data acquisition, a
point-in-time data platform, a feature factory, a strategy registry, a backtest
engine, supervised and reinforcement learning, portfolio and risk management, an
orchestrator, and a Telegram interface. Written as a list, that reads like a
distributed system. It is worth deciding now whether it is one, because the
answer changes how every later phase is built.

The operating context argues strongly that it is not. GLOBIN runs on **one**
Windows machine with **one** operator, at a rate of tens of trades per hour, on
a zero-budget runtime (ADR-0003). Nothing in that description benefits from
independent deployment, horizontal scaling, or a network hop between
subsystems. [`../ARCHITECTURE_PRINCIPLES.md`](../ARCHITECTURE_PRINCIPLES.md)
principle 8 already establishes that reliability outranks performance here:
uptime, crash recovery and reconciliation are the design targets, and
microseconds are not.

Distribution would also add exactly the failure modes the system can least
afford. A broker or an inter-process boundary between the risk check and the
order submission introduces a partition where a position can be opened while
the component that would have stopped it is unreachable. On a single host, that
risk is bought for no gain.

The countervailing pressure is real, though. A single process means a defect
anywhere can stop everything, and a 320-phase programme accumulating in one
namespace is how a codebase becomes unnavigable.

## Decision

**GLOBIN is a modular monolith:** one repository, one Python distribution, one
process, with boundaries enforced at package level rather than at process level.

Specifically:

- All production code lives in the single `globin` package under `src/`
  (ADR-0001), organised into layers by [ADR-0014](0014-layered-ports-and-adapters-and-inward-dependencies.md).
- Isolation between subsystems is achieved by package boundaries and typed
  interfaces, checked by tests, not by network protocols.
- **No message broker, container orchestrator, service mesh, remote procedure
  framework or service registry** is introduced. None is needed on one host, and
  each would breach the zero-budget runtime rule or add an operational surface
  with no operator to run it.
- Where a component might one day need to run separately, the seam is the
  **port** it is reached through. Splitting a process later means writing a new
  adapter, not restructuring the core.

This decision covers *deployment topology*. Threading, process supervision and
isolation between long-running subsystems are a separate question that
[`../../ROADMAP.md`](../../ROADMAP.md) assigns to Phase 261; this record does
not pre-empt it, and choosing a monolith does not mean choosing a single thread.

## Consequences

- A defect in any module can bring down the whole process. That is accepted, and
  it is why Phases 257-272 concentrate on supervision, restart and
  reconciliation rather than on isolation.
- Subsystems cannot be scaled or deployed independently. On a single-operator,
  single-host system there is nothing to scale them onto.
- Calls between subsystems are ordinary typed Python calls, so `mypy --strict`
  checks the whole graph. A distributed design would have replaced that with
  serialisation contracts, which are checked at runtime if at all.
- There is no version skew between components, no partial deployment, and no
  distributed tracing requirement. A stack trace crosses the entire system.
- The risk of an unnavigable single namespace is real and is not addressed by
  this record. It is addressed by ADR-0014, which is why the two were decided
  together.
- Nothing here is free to reverse. Splitting a process later costs a new
  adapter, a transport, and a failure mode that did not previously exist — but
  it costs that once, for one component, rather than for all of them now.

## Alternatives Considered

**Microservices from the start.** Rejected. The stated benefits — independent
deployment, independent scaling, team autonomy, fault isolation — require
respectively: a deployment pipeline, more than one host, more than one
contributor, and a tolerance for partial failure. GLOBIN has none of the first
three, and the fourth is actively undesirable in a component that moves money.

**A message broker between subsystems inside one host.** Rejected. It is the
common middle path and it is genuinely tempting, because it decouples producers
from consumers and gives replay for free. It was rejected because it adds a
runtime dependency and a durable store to operate, and because it converts
compile-time-checked calls into runtime-checked messages. The decoupling it
provides is available from ports at no such cost. If event replay later proves
necessary for research reproducibility, that is a data-platform decision for
Phases 097-112, not a transport decision now.

**One process per subsystem, coordinated by the orchestrator.** Rejected as
premature rather than wrong. It is the natural evolution if a heavy workload —
model training is the likely candidate — turns out to destabilise the trading
loop. Phase 261 owns that question, and it should be answered with a measurement
rather than an assumption. This record deliberately leaves the seam in place for
it.

**A plugin architecture with dynamically discovered components.** Rejected.
Dynamic discovery defeats static analysis, which is the main advantage a
monolith has, and it makes the composition of the running system unknowable
without executing it.

## Risks and Trade-offs

The characteristic failure of this choice is the big ball of mud: a monolith
whose modules were supposed to stay separate and did not, discovered only when
someone tries to change one. Package boundaries that exist only by convention
always erode, because nothing fails when they are crossed.

This is why the decision is not being made on its own. ADR-0014 defines the
boundaries and Phase 003 ships tests that fail when one is crossed. Without that
enforcement this record would be an aspiration, and the honest assessment is
that it would not survive twenty bands.

The second risk is that a genuinely heavyweight workload — reinforcement
learning is the candidate — makes single-process operation untenable, and the
discovery comes late. The signal to watch for is the trading loop's latency or
reliability degrading while a research workload runs; Phase 205 benchmarks that
workload specifically, and Phase 261 owns the response.

## References

- [`../PROJECT_CHARTER.md`](../PROJECT_CHARTER.md) — the operating context this
  decision rests on: one host, one operator, zero budget.
- [`../ARCHITECTURE_PRINCIPLES.md`](../ARCHITECTURE_PRINCIPLES.md) — principle 8,
  reliability outranks performance.
- [`0003-zero-budget-open-source-dependency-policy.md`](0003-zero-budget-open-source-dependency-policy.md)
  — why paid or heavyweight infrastructure is out of scope.
- [`0014-layered-ports-and-adapters-and-inward-dependencies.md`](0014-layered-ports-and-adapters-and-inward-dependencies.md)
  — the boundaries that make this decision survivable.
- [`../research/phase_003_sources.md`](../research/phase_003_sources.md) — S-01
  to S-03 on the C4 abstractions used to describe the result.

## Supersedes

None.

## Superseded By

None.
