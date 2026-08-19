# Granularity review — Phases 017-032

Whether the environment band was drawn at a granularity that describes the work.

`ROADMAP.md` assigns this review to Phase 032 by name, and six accepted decisions
repeat the assignment — [ADR-0064](../adr/0064-phase-025-widens-to-deliver-the-runtime-watchdog.md),
[ADR-0067](../adr/0067-phase-026-widens-to-deliver-the-telemetry-foundation.md),
[ADR-0070](../adr/0070-phase-027-widens-to-deliver-the-loopback-diagnostics-surface.md),
[ADR-0073](../adr/0073-phase-028-widens-to-deliver-the-environment-capability-inventory.md),
[ADR-0076](../adr/0076-phase-029-widens-to-deliver-the-dependency-attestation.md) and
[ADR-0079](../adr/0079-phase-030-widens-to-deliver-the-configuration-evidence-surface.md).

This document is the prose half of [`scope-amendments.toml`](scope-amendments.toml),
and every count in it is recomputed from that ledger by
`tests/contract/test_granularity_contract.py`. That binding is not decoration.
`ROADMAP.md` says of its own amendment count: *"Nothing tests it, which is why it
drifted and why it is worth reading sceptically."* It drifted twice — reading
*seven* while listing eight, then *thirteen* while listing eleven with the tenth
filed below the eleventh. A review of that count that nothing checked would have
been the third instance of the same defect rather than an answer to it.

**This review records findings. It changes no roadmap row for Phases 033-320.**

---

## What is being scored

[ADR-0021](../adr/0021-phase-005-widens-to-include-the-test-foundation.md) never
uses the word *condition* and never numbers anything. The four-part form every
later record cites is `ROADMAP.md`'s own restatement: an amendment must be able
to say **nothing displaced, nothing deferred, no phase owns the work, and the two
halves need each other**. That restatement is what the programme actually
applied, so it is what is scored here.

Seventeen amendments have been made. Three predate the test — the first two came
before ADR-0021, and the third *is* ADR-0021, which created the test in the act
of being the amendment that needed one. Fourteen are scored.

---

## The scores

**The table runs past the band this review was written for**, and deliberately.
The tally below is recomputed from every *scored* amendment in the ledger rather
than from the ones inside Phases 017-032, so a later amendment that did not appear
here would make the counts wrong. Phase 033 added the first row past the band and
Phase 034 the second; the findings are still about the environment band, and each
new row is one more application of the same test rather than a claim about a
different band.

| # | Phase | Record | Score |
|:-:|:-----:|--------|:-----:|
| 4 | 017 | [ADR-0051](../adr/0051-phase-017-absorbs-interpreter-pinning-and-the-environment-lifecycle.md) | 2/4 |
| 5 | 021 | [ADR-0056](../adr/0056-phase-021-widens-to-deliver-the-application-bootstrap.md) | 2/4 |
| 6 | 022 | [ADR-0057](../adr/0057-phase-022-widens-to-deliver-the-runtime-filesystem-and-lifecycle.md) | 1/4 |
| 7 | 023 | [ADR-0060](../adr/0060-gpu-capability-is-detected-and-the-runtime-explains-itself.md) | 1/4 |
| 8 | 024 | [ADR-0061](../adr/0061-phase-024-widens-to-deliver-runtime-health-and-support-bundles.md) | 1/4 |
| 9 | 025 | [ADR-0064](../adr/0064-phase-025-widens-to-deliver-the-runtime-watchdog.md) | 1/4 |
| 10 | 026 | [ADR-0067](../adr/0067-phase-026-widens-to-deliver-the-telemetry-foundation.md) | 1/4 |
| 11 | 027 | [ADR-0070](../adr/0070-phase-027-widens-to-deliver-the-loopback-diagnostics-surface.md) | 2/4 |
| 12 | 028 | [ADR-0073](../adr/0073-phase-028-widens-to-deliver-the-environment-capability-inventory.md) | 2/4 |
| 13 | 029 | [ADR-0076](../adr/0076-phase-029-widens-to-deliver-the-dependency-attestation.md) | 2/4 |
| 14 | 030 | [ADR-0079](../adr/0079-phase-030-widens-to-deliver-the-configuration-evidence-surface.md) | 4/4 |
| 15 | 031 | [ADR-0082](../adr/0082-phase-031-widens-to-deliver-the-user-scoped-secret-vault.md) | 1/4 |
| 16 | 032 | [ADR-0084](../adr/0084-phase-032-widens-to-deliver-the-bootstrap-provisioning-surface.md) | 2/4 |
| 17 | 033 | [ADR-0086](../adr/0086-phase-033-widens-to-deliver-the-binance-api-reality-registry.md) | 2/4 |
| 18 | 034 | [ADR-0088](../adr/0088-phase-034-widens-to-deliver-the-rest-transport-substrate.md) | 2/4 |
| 19 | 035 | [ADR-0090](../adr/0090-phase-035-widens-to-deliver-the-rest-authentication-layer.md) | 2/4 |

Mean 1.73 of four.

---

## Finding 1 — two of the four conditions carry almost no information

This is the review's central result, and it is arithmetic rather than argument.

| Condition | Met |
|---|:---:|
| `nothing_displaced` | 1/16 |
| `nothing_deferred` | 16/16 |
| `no_phase_owns_it` | 1/16 |
| `halves_need_each_other` | 10/16 |

**One condition has never once failed.** Every amendment delivered its titled
scope in full. Nothing was ever traded away to make room, in sixteen
consecutive applications of a test whose job is to discriminate.

**Two conditions have failed all but once**, and the once is the same phase for
both — Phase 030, the only amendment to score four.

So across fifteen amendments the test has one condition that always passes, two
that almost always fail, and one that genuinely varies. Its effective resolution
is close to a single bit. That is why a four and a one arrived in consecutive
phases (030 and 031) without anything having changed about how carefully the work
was scoped: the score is nearly determined before the amendment is written.

[ADR-0082](../adr/0082-phase-031-widens-to-deliver-the-user-scoped-secret-vault.md)
predicted this outcome and named the signal — that Phase 032 would find it could
not conduct the review without first asking whether the test is worth keeping.
It could not, and this is that finding.

**No replacement is proposed here.** Designing a governance test from a single
band's evidence is the same error as the one being diagnosed, and it is Phase
048's to do with two bands in front of it.

---

## Finding 2 — the band is not drawn wrong; a subject is missing

The tempting conclusion from fifteen amendments is that the rows are too coarse
or too fine. Neither holds.

**The band range and subject are intact.** *Nothing deferred* was met 15/15:
every phase delivered what its title promised. A band whose rows were too large
would show deferrals, and there are none.

**The rows describe provisioning steps. The work that arrived is the running
application's substrate.** Sixteen rows say survey, pin, install, detect,
provision, resolve, prompt. What eleven consecutive phases actually delivered
alongside them was a runtime filesystem, process diagnostics, a health surface, a
watchdog, telemetry, a loopback endpoint, configuration evidence and a
degradation posture. Two different subjects — and the band has sixteen rows for
the first and **zero rows for the second**.

That is the defect. Eleven phases had somewhere to put their titled work and
nowhere to put the rest, so it went where the work was happening.
[ADR-0073](../adr/0073-phase-028-widens-to-deliver-the-environment-capability-inventory.md)
saw the shape first and stated it precisely: that phase's brief and its roadmap
row "described two different subjects with no overlap at all, which is a different
failure from a brief that describes work an earlier phase already did."

**A missing subject is worse than a widening, because a widening is visible and a
missing subject is not.** A widening produces an ADR somebody must write and
defend. A missing subject produces thirteen of them, each individually
defensible, and the pattern is only visible from where this review stands.

---

## Finding 3 — seven collisions are with a phase *title*, not a purpose

Most displacement lands on a phase's purpose text. Seven landed on its title,
which is a stronger claim of ownership and is recorded separately. Four of the
seven arrived at once, in the seventeenth.

| Phase | Title | Collided by | Record |
|:-----:|-------|:-----------:|--------|
| 263 | Supervisor and Watchdog | 025 | ADR-0064 |
| 280 | Operational Metrics Collection | 026 | ADR-0067 |
| 292 | Credential Collection and Persistence Flow | 031 | ADR-0082 |
| 034 | Official Documentation Ingestion and Change Tracking | 033 | ADR-0086 |
| 035 | Environment Classification Model | 033 | ADR-0086 |
| 036 | Product and Environment Capability Matrix | 033 | ADR-0086 |
| 037 | Base URL and Endpoint Registry | 033 | ADR-0086 |

In each case the collision was refused rather than rebuilt, and the refusal is in
the record: Phase 025 delivered a watchdog with no driver, no recovery and no
restart; Phase 026 declared and bounded metrics without collecting, retaining,
dashboarding or alerting; Phase 031 stored credentials without collecting them,
collection being Phase 029's and already complete.

---

## Finding 4 — four overlaps are with phases that had already shipped

Displacing work into a phase that has not started is resequencing. Overlapping
one that is `Complete` is different in kind, because the phase it overlaps cannot
absorb the change or argue with it.

| Amendment | Phase | Overlaps | Which is |
|:---------:|:-----:|:--------:|----------|
| 7 | 023 | 006 | *Structured Logging Foundation* |
| 13 | 029 | 020 | *Dependency Resolution and Lockfile Strategy* |
| 15 | 031 | 028, 029 | the secret store and the credential flow |

[ADR-0060](../adr/0060-gpu-capability-is-detected-and-the-runtime-explains-itself.md)
had to concede the first and set the rule every later one inherited: an amendment
overlapping a completed phase must say which one. All three did.

---

## Finding 5 — displacement concentrates on phases that have not started

Phase 030 was named by four separate amendments — the sixth, seventh, eighth and
ninth — before it began. It *did* arrive to find its subject partly built, which
is the outcome this review predicts for the phases below. Phases 280 and 282 were
each named three times; 262, 266 and 315 twice each.

By band, the displacement lands overwhelmingly on Phases 257-272 (*Autonomous
Orchestration*), which is touched at six distinct rows.

That is consistent with Finding 2 rather than separate from it. The runtime
substrate has no rows in this band, and the phases that *do* own substrate-shaped
work are three bands away.

---

## What a later phase will find partly built

The ledger's `[[inheritance]]` table, which is the most useful thing this review
produces. Sixteen phases have not started and already have part of their subject
built. Each row names both what exists **and** what is deliberately absent,
because a phase told only what exists will rebuild the boundary, and a phase told
only what is missing will rebuild what is there.

`test_granularity_contract.py` asserts every phase in that table is still
`Planned`, so a row survives exactly as long as it is true.

The three sharpest, restated here because they are the ones most likely to be
met without warning:

- **Phase 263 — Supervisor and Watchdog.** The heartbeat registry, the suspect
  threshold, the stall evidence and the escalation to a hard exit all exist.
  There is no driver, no recovery, no restart, no subsystem ordering and no
  draining.
- **Phase 280 — Operational Metrics Collection.** The metric contract, the
  bounded registry, both provider bridges and the scrape route exist. **Nothing
  collects, retains, dashboards or alerts.**
- **Phase 292 — Credential Collection and Persistence Flow.** The store, the
  vault, the six-verb command group and the permission model exist. Collection is
  Phase 029's and is already complete, so this phase's title describes work that
  has been done by two other phases.

---

## What this review does not do

**It does not rewrite a roadmap row.** The owner's instruction was findings only,
and there is a reason beyond instruction to be glad of it: a review conducted
inside a phase that is itself the sixteenth amendment is not a disinterested one.
This document's evidence should be weighed by Phase 048, which will have two
bands and no stake in either.

**It does not propose a replacement for ADR-0021's test.** See Finding 1.

**It does not excuse the phase that wrote it.** Phase 032 is the sixteenth
amendment, scores two of four, and is in the ledger on the same terms as the
twelve before it. That this review is written by a phase it must score is stated
rather than worked around, and it is why no replacement test is proposed and no
roadmap row is rewritten.

---

## Related documents

| Question | Phase |
|---|---|
| The amendment ledger itself | 032, delivered — [`scope-amendments.toml`](scope-amendments.toml) |
| Whether the environment band is certified | 032 |
| Whether the *foundation* band was certified | 016, delivered — [`../release/FOUNDATION_ACCEPTANCE.md`](../release/FOUNDATION_ACCEPTANCE.md) |
| Whether ADR-0021's test should be replaced | 048 |
| Whether the runtime substrate deserves rows of its own | 048 |
