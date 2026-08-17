# ADR-0070 — Phase 027 widens to deliver the loopback diagnostics surface, over the roadmap's own refusal

## Status

Accepted — Phase 027.

**Date:** 2026-08-17

## Context

`ROADMAP.md` row 027 is *Environment Variable and Profile Resolution*, and Phase 026
deferred precedence to it in those words: *"a search order is a precedence and
precedence is Phase 027's"*. Two documents carry deferral rows naming this phase —
[`../CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md) and
[`../security/SECRET_STORE_CONTRACT.md`](../security/SECRET_STORE_CONTRACT.md).

The owner asked for something else: a loopback-only diagnostics HTTP surface —
liveness, readiness, a redacted runtime health projection, and a Prometheus/OpenMetrics
scrape endpoint, bounded and read-only.

**This is the eleventh scope amendment, and the roadmap refuses one in advance.**
`ROADMAP.md` says, of the tenth:

> The signal ADR-0064 named has fired. That record said a tenth amendment before the
> band closes at Phase 032 would be evidence the roadmap is being treated as a
> backlog, and that the right response is to question the roadmap's granularity rather
> than to write an eleventh argument. **Phase 032 must therefore examine whether
> Phases 017-032 were drawn at a granularity that describes the work, with all ten
> amendments in front of it.** An eleventh before then is not another argument to be
> weighed.

That sentence was put to the owner verbatim, together with the two alternatives it
implies — bring the granularity review forward now, or deliver the roadmap's titled
scope alone and leave the surface to Phase 032's examination. **The owner chose to
proceed with the eleventh amendment.** This record exists to say so plainly rather
than to argue around it.

## Decision

Phase 027 delivers **both halves**:

1. **The roadmap's own scope.** Deterministic precedence between defaults, the four
   configuration documents, environment variables and launcher selection. The document
   order is one function, `config_layout.precedence()`; the profile order is one
   function, `config_layout.profile_from()`; the chain is assembled in one place,
   `composition.build_config_sources()`. Both deferral rows are closed.
2. **The loopback diagnostics surface**, as the eleventh scope amendment. Recorded in
   [ADR-0072](0072-the-diagnostics-surface-is-loopback-only-read-only-and-bounded-by-construction.md).

## Consequences

**ADR-0021's four conditions, restated in full and scored.** An amendment must show
that:

1. *Nothing is deferred.* **Met.** Row 027's own scope is delivered, not displaced.
   The precedence question Phase 026 handed forward is answered, and the two documents
   that named this phase now name it as delivered.
2. *No other title changes.* **Met.** No row is retitled and no band range moves.
3. *Work is not displaced into a phase that owns it.* **Failed, and worse than the
   tenth.** Phase 280 is *Operational Metrics Collection* and Phase 315 is *Live
   Monitoring and Escalation*; a `/metrics` endpoint is closer to 280 than the
   telemetry *declaration* Phase 026 delivered was. Phase 030 is *Bootstrap Health
   Check Suite*, and this phase strengthened preflight. The collision is refused
   rather than rebuilt — 280's verb is *collect*, 315's is *escalate*, and this phase
   neither collects, retains, dashboards nor alerts, with the owning phases named in
   [`../engineering/DIAGNOSTICS_ENDPOINT.md`](../engineering/DIAGNOSTICS_ENDPOINT.md).
   But the overlap is real, and calling it anything else would be the normalisation
   ADR-0067 warned about.
4. *The two halves do not need each other.* **Failed.** They are independent
   subsystems sharing one commit. What they do share is that the surface's settings
   arrive through the machinery the first half built, and the first half's fail-closed
   validation is what stops the surface binding a non-loopback address — so the diff
   is coherent even though the halves are not coupled.

**It scores two of four, and the two it fails are the two the tenth also failed.**
ADR-0067 recorded that "two in a row is materially worse than a repeat of an earlier
shape"; three in a row is worse again, and the roadmap had already said so before this
phase started.

**What this phase did *not* do is answer the granularity question.** It remains
Phase 032's, with eleven amendments in front of it rather than ten. This record cites
neither ADR-0067 nor the series as precedent, because ADR-0067 forbade exactly that:
*"An eighth amendment can cite neither this one nor the series."* The only thing
carrying this amendment is the owner's decision, taken with the refusal in front of
them.

**A twelfth may cite nothing at all.** Not this record, not the series, and not the
owner's having overridden the refusal once. The roadmap's instruction stands unchanged
and unweakened by this phase: the response to wanting another amendment is to question
the granularity, and Phase 032 is where that happens.

## Alternatives Considered

**Bring the granularity review forward into this phase.** What `ROADMAP.md:298` asks
for, and the governance-correct answer: re-draw Phases 017-032 so that titles describe
the work, then deliver the surface into a row whose title names it. Refused by the
owner. It is a large restructuring of a band that is two-thirds delivered, and it would
have made a phase about configuration precedence into a phase about the roadmap.

**Deliver only the roadmap's titled scope.** Clean, requires no amendment, and refuses
the owner's actual request. Refused for that reason.

**Deliver only the surface, and move row 027 forward.** Would have made the roadmap's
own row wrong rather than merely widened, moved the frontier, and still left the
precedence question open for a third phase running.

## Risks and Trade-offs

**The amendment series is now the strongest argument against itself.** Eleven
amendments across a band of sixteen phases is not a sequence of exceptions; it is
evidence that the band was drawn at the wrong granularity, which is precisely what the
roadmap says and precisely what this phase did not fix.

**A large phase is a phase whose parts get less attention than they would alone.**
Mitigated by keeping the two halves separable in review — different modules, different
documents, different test files — and by the fact that the second half's own decisions
are in their own ADRs rather than here.

**Preflight became stricter, which can fail a host that used to pass.** Before this
phase `bootstrap check` validated the declared defaults rather than the resolved
configuration, so a bad document or variable passed the gate and failed at start-up.
That was a hole and closing it is correct, but it means an installation with an invalid
configuration will now be refused earlier and louder than it was.

## References

- `ROADMAP.md`, the scope-amendment log and rows 027, 030, 280, 315.
- [ADR-0021](0021-phase-005-widens-to-include-the-test-foundation.md) — the four
  conditions restated above.
- [ADR-0064](0064-phase-025-widens-to-deliver-the-runtime-watchdog.md) — the record
  that named the signal.
- [ADR-0067](0067-phase-026-widens-to-deliver-the-telemetry-foundation.md) — the tenth,
  which forbade a successor citing it.
- [ADR-0071](0071-configuration-precedence-is-declared-and-an-environment-variable-is-a-derived-name.md)
  — the first half's decisions.
- [ADR-0072](0072-the-diagnostics-surface-is-loopback-only-read-only-and-bounded-by-construction.md)
  — the second half's.

## Supersedes

Nothing.

## Superseded By

Nothing.
