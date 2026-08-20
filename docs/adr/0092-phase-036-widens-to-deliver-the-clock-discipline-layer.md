# ADR-0092 — Phase 036 delivers the clock discipline layer, and rows 036 and 040 are rewritten

## Status

Accepted — Phase 036.

**Date:** 2026-08-20

## Context

`ROADMAP.md` row 036 reads *Product and Environment Capability Matrix*. Row 040
reads *Server Time Synchronization and Drift Control*. The work this phase was
briefed to do is row 040's, and the package says so in eight places —
[`ports/clock.py`](../../src/globin/ports/clock.py),
[`adapters/clock.py`](../../src/globin/adapters/clock.py),
[`domain/auth_timing.py`](../../src/globin/domain/auth_timing.py),
[`TIME_POLICY.md`](../TIME_POLICY.md) twice,
[`REST_AUTHENTICATION.md`](../engineering/REST_AUTHENTICATION.md),
[`DEGRADED_OPERATION.md`](../engineering/DEGRADED_OPERATION.md) and
[`phase_035_sources.md`](../research/phase_035_sources.md).

**Row 036's own subject has already shipped**, which is what makes this amendment
different from the three before it. The seventeenth
([ADR-0086](0086-phase-033-widens-to-deliver-the-binance-api-reality-registry.md))
gave the capability matrix to Phase 033: `binance-api-reality.toml` records every
product against every environment, and `globin api-reality capability` queries it.
The eighteenth
([ADR-0088](0088-phase-034-widens-to-deliver-the-rest-transport-substrate.md))
gave the *binding refusal* to Phase 034: `resolve()` runs ten gates and refuses an
unmapped combination, which
[ADR-0087](0087-the-api-reality-registry-is-declared-with-provenance-and-drift-is-measured-in-two-regimes.md)
had explicitly left to "Phase 036 makes it binding". Both halves of row 036 are
therefore delivered, and building them again would be the second copy of a rule
[`SOURCE_OF_TRUTH.md`](../engineering/SOURCE_OF_TRUTH.md) refuses.

So the usual resolution — *deliver both halves* — is not available. There is no
second half left to deliver.

The pressure that forces the timing work now is concrete rather than scheduled.
Phase 035 built the signing layer and left `sign_request` taking a wall-clock
`Instant`. On the declared host `time.get_clock_info('time')` reports
`adjustable=True`: the Windows Time Service, an NTP step and an operator all move
that clock without announcing it. A signed request built on a stepped clock is
rejected with `-1021`, and a clock quietly running fast produces timestamps in the
venue's future — the one direction `recvWindow` does not forgive. Phase 035's own
ledger records the venue's timing rule and says plainly that it is *"recorded rather
than implemented … it names `serverTime`, which GLOBIN does not have"*
([`phase_035_sources.md`](../research/phase_035_sources.md) S-02).

## Decision

**Phase 036 delivers the multi-product clock discipline layer** — clock domains,
an RTT-aware offset estimator with a stated error bound, a five-state health
machine, wall-clock jump detection, a trusted timestamp generator, a central
`recvWindow` policy, a seven-gate signing admission, and a bounded `-1021`
recovery seam.

**It delivers nothing of its own title**, because its title's work shipped in
Phases 033 and 034.

**Rows 036 and 040 are both rewritten.** Row 036 is rewritten to describe what the
phase did; row 040 is rewritten because a reader of it would otherwise plan a phase
whose subject had already shipped — the exact reasoning the eighteenth amendment
gave for rewriting rows 034 and 045.

### The four conditions

| Condition | Verdict |
|---|---|
| Nothing displaced | **FAILED** — row 040 loses its whole subject |
| Nothing deferred | **MET** — every half ships in one commit |
| No phase owns the work | **FAILED** — row 040 owns it by title, and the package named it in eight places |
| The two halves need each other | **MET, vacuously** — there is only one half |

Two of four, the same score as the seventeenth, eighteenth and nineteenth. The
fourth condition is recorded as *vacuously met* rather than as met, because
claiming that two halves need each other when only one exists would be scoring a
condition that was not tested.

### On rewriting a third row

The eighteenth amendment called its own rewrite *"the first exception to it —
recorded as an exception rather than as precedent"*, and the nineteenth declined to
rewrite row 038 on the grounds that *"doing it again three phases later would make
the exception a habit"*.

This record rewrites two rows anyway, and the reason is a difference in kind rather
than a weakening of the rule. The nineteenth declined because row 038's title —
*Request Signing and Authentication* — still covered real open work: permission
verification. Neither row here does. Row 036's subject is delivered and row 040's
subject is delivered by this commit, so leaving either text intact would leave the
roadmap describing two phases with nothing to do. **A displacement note can be
honest about work that moved; it cannot be honest about work that no longer
exists.**

## Consequences

**The roadmap now carries three rewritten rows** — 034, 045 and now 036 and 040,
which is four across two amendments. The granularity review reserved rewriting for
Phase 048, and this is the second departure from that. Phase 048 inherits both.

**Phase 040 is now free**, and `ROADMAP.md` says what it holds instead rather than
leaving it blank: the band's own finding, recorded by the sixteenth amendment, is
that this programme has rows for provisioning steps and none for the running
application's substrate. Row 040 becomes the first row to name that subject.

**`sign_request` changed shape**, which is a breaking change to a Phase 035 public
function. It took `moment: Instant` and `policy: AuthPolicy`; it now takes
`timing: TimingContext`. That is the deliverable rather than a side effect — see
[ADR-0093](0093-server-time-is-estimated-from-the-lowest-round-trip-and-a-window-is-never-widened.md).

**A defect in Phase 034 was repaired in passing.** Reading `errors.md` for `-1021`
found `-1006 UNEXPECTED_RESP`, documented as *"Execution status unknown"* and
classified by GLOBIN as a confirmed failure. That is the exact fact
[ADR-0089](0089-an-unknown-outcome-is-preserved-and-a-second-module-may-reach-a-socket.md)
exists to preserve. The row is added here rather than deferred to Phase 044,
because the source that revealed it is one this phase legitimately needed.

**No new exit code.** `globin clock` reuses the health triad — `0`, `3`, `1` — that
`diagnostics snapshot` and `drift` already speak. **26 stays free.**

**No new runtime dependency, and no new absent-safe factory.** The seven declared
in `degradation-contract.toml` are unchanged.

## Alternatives Considered

**Deliver the capability matrix as row 036 states.** Rejected because it is
delivered. Writing a second matrix beside `binance-api-reality.toml` would create
two answers to *which products support which environments* and put the burden of
keeping them equal on a test that would then be the only thing standing between
them — which is what `SOURCE_OF_TRUTH.md` refuses.

**Deliver the clock layer alongside the one genuinely unbuilt part of
[ADR-0006](0006-product-and-environment-capability-matrix.md)** — its rule 4, that
paper trading is a per-product composition rather than a global mode. Rejected on
size and on ownership: that work needs the credential register Phase 039 owns and
the endpoint registry Phase 037 owns, and building it here would displace two more
rows to make an amendment score better on one condition.

**Record a displacement note and leave both row texts intact**, as the seventeenth
and nineteenth did. Rejected because it is the option that is actually dishonest
here: a reader planning row 040 from its text would plan a phase whose subject
shipped in this commit, and the eighteenth amendment already refused that reasoning
for row 045.

**Renumber the programme so the work lands in row 040.** Rejected outright. Band
ranges, phase numbers and the sixteen-phase band width are fixed by
`project_contract.py` and asserted by test; twenty amendments have left them
untouched, and a renumbering would invalidate every recorded phase reference in the
repository.

## Risks and Trade-offs

**The characteristic failure mode is precedent erosion.** Four rewritten rows
across two amendments is a pattern rather than an exception, and the next phase that
finds its title inconvenient has a shorter argument to make than this one did. The
observable signal is a fifth rewrite whose justification is *the work moved* rather
than *the work no longer exists* — the distinction this record turns on. Phase 048's
review is where that should be caught.

**A second risk is specific to the finding rather than the amendment.** This record
claims row 036's subject is fully delivered. That claim rests on reading ADR-0086
and ADR-0088 rather than on a test, because no test asserts *what a roadmap row
means*. If some part of the capability matrix turns out to be missing, it will be
found by the phase that needs it, and this record will read as having been too
confident. The mitigation is that the two artefacts are queryable —
`globin api-reality capability` and `globin rest endpoints` — so the claim is
checkable by anybody who doubts it.

## References

- [ADR-0006](0006-product-and-environment-capability-matrix.md) — the matrix this
  row was created to build, and the rule 4 this phase did not take.
- [ADR-0086](0086-phase-033-widens-to-deliver-the-binance-api-reality-registry.md) —
  the seventeenth amendment, which took the matrix.
- [ADR-0088](0088-phase-034-widens-to-deliver-the-rest-transport-substrate.md) —
  the eighteenth, which took the binding refusal and rewrote two rows.
- [ADR-0090](0090-phase-035-widens-to-deliver-the-rest-authentication-layer.md) —
  the nineteenth, which declined to rewrite a row and said why.
- [ADR-0093](0093-server-time-is-estimated-from-the-lowest-round-trip-and-a-window-is-never-widened.md) —
  what this phase actually decided about clocks.
- [`GRANULARITY_REVIEW.md`](../engineering/GRANULARITY_REVIEW.md) and
  [`scope-amendments.toml`](../engineering/scope-amendments.toml) — the ledger this
  amendment is the twentieth row of.
- [`CLOCK_DISCIPLINE.md`](../engineering/CLOCK_DISCIPLINE.md) — the delivered layer.
- [`phase_036_sources.md`](../research/phase_036_sources.md) — the evidence.

## Supersedes

None.

## Superseded By

None.
