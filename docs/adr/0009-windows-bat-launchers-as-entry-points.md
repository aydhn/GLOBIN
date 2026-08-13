# ADR-0009 — Two Windows BAT launchers are the final user entry points

## Status

Accepted — Phase 001. Implementation deferred to Phases 289-304.

## Context

GLOBIN is operated by a single person on a Windows machine, not by a team with
a deployment pipeline. The operating interface has to be usable at three in the
morning when something has gone wrong, without recalling command-line flags or
activating a virtual environment by hand.

There is also a failure pattern worth naming in advance. Systems that offer a
convenient launcher often keep a second, hidden switch that actually controls
whether real orders are sent — a configuration flag, an environment variable, a
constant in a source file. The result is a documented entry point that does not
do what it says, and an operator who believes they are trading live when they
are not, or the reverse. Either direction is a serious defect.

## Decision

GLOBIN will ultimately expose exactly two user-facing entry points:

- `start_windows_paper.bat`
- `start_windows_live.bat`

**Neither is implemented in Phase 1.** This ADR records their contract so later
phases implement something already agreed rather than improvising.

Each launcher is responsible for: locating the repository reliably; validating
Windows prerequisites and locating Python; validating or creating `.venv`;
installing and verifying locked dependencies; checking hardware and NVIDIA or
CUDA capability where applicable; running prerequisite tests and health checks;
selecting the correct runtime profile; interactively requesting any missing
credentials and storing them through the approved local secret mechanism, never
in the repository; activating the environment; launching the long-lived
orchestrator; starting the required subsystems in dependency order; and staying
alive for long-duration operation.

Two rules govern their behaviour:

1. **The selected profile is authoritative.** When `start_windows_live.bat`
   selects the live profile and the integration, account capability, credentials,
   permissions and mandatory preflight and risk checks all pass, the system sends
   real orders. There is no additional hidden toggle that quietly makes the
   documented live launcher inert.
2. **"All features active" means enabled and scheduled, not simultaneous.** The
   orchestrator enables the subsystems appropriate to the profile and runs them
   according to explicit scheduling, dependency and resource rules. Retraining,
   optimisation, backtesting and research refreshes are scheduled work, not an
   uncontrolled loop competing for the same CPU and GPU.

Preflight failure blocks startup. A launcher that cannot verify its
preconditions must refuse to start rather than proceed hopefully.

## Consequences

- Phases 289-304 implement the launchers, and Phase 289 begins by finalising
  this contract in detail.
- The launchers are substantial programs, not thin wrappers, so they need their
  own tests and failure handling.
- Because the live launcher genuinely trades, its preflight gate is a safety
  component and is treated with the same seriousness as the risk gate in
  ADR-0008.
- Any future change that introduces a hidden override of profile selection
  contradicts this ADR and must be rejected or explicitly supersede it.
