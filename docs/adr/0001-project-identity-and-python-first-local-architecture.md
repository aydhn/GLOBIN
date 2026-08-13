# ADR-0001 — Project identity and Python-first local architecture

## Status

Accepted — Phase 001.

## Context

GLOBIN is intended to run on the owner's own Windows computer: consumer-grade
hardware, a possible NVIDIA GPU, and roughly 100 Mbps wired internet. The
expected trading cadence reaches tens of trades per hour at most, and the
process may run continuously for days.

That profile is unlike a high-frequency trading system. Chasing microsecond
latency would demand co-location, kernel bypass networking and a compiled
language — and would buy nothing at this cadence. The genuine risks here are
different: a process that dies overnight, a state divergence nobody notices, a
backtest that quietly lied.

A name and import namespace also need fixing now, because every later phase
and every future coding agent will assume them.

## Decision

The project is named **GLOBIN**, the repository is `GLOBIN`, and the Python
import namespace is `globin`. These are immutable and are encoded in
`src/globin/project_contract.py` where tests assert them.

The implementation is **Python-first and local-first**. The system targets a
single Windows host. Architecture optimises for reliability, correctness and
auditable evidence rather than latency. A `src/` layout is used so that tests
run against installed-shaped imports rather than accidental relative paths.

Native or accelerated components are permitted where measurement justifies
them, but they are optimisations beneath a Python architecture, not a
replacement for it.

## Consequences

- Latency-driven design techniques are explicitly out of scope. Proposals
  justified only by speed at this cadence should be rejected.
- Long-running process health, crash recovery and reconciliation become
  first-class concerns, which is why Phases 257-272 exist as a full band.
- Single-host operation bounds the achievable scale, and that limit must be
  acknowledged in capacity modelling (Phase 150) rather than wished away.
- Renaming the project or package later would break the contract tests
  deliberately, forcing the change to be explicit rather than incidental.
