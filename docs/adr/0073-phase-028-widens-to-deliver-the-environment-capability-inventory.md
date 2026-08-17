# ADR-0073 — Phase 028 widens to deliver the environment capability inventory

## Status

Accepted — Phase 028.

**Date:** 2026-08-18

## Context

`ROADMAP.md` row 028 is *Local Secret Storage Mechanism*: "Implement the approved local
secret store so credentials never reach the repository or plain configuration." That
scope is unusually well prepared. Phase 015 wrote the rules
([ADR-0048](0048-a-secret-lives-outside-the-tree-and-is-redacted-before-a-record-exists.md)),
Phase 020 measured what Windows offers and wrote
[`../security/SECRET_STORE_CONTRACT.md`](../security/SECRET_STORE_CONTRACT.md), and
Phase 021 cut the seam — `SecretProbe`, `SecretReadiness` and `secrets_outcome` exist
and pass vacuously, with a comment naming "the day Phase 028 puts a store behind this".

The owner asked for something else: a Windows runtime environment capability inventory —
native versus process architecture, WOW64 and emulation state, bounded toolchain
discovery, a redacted compatibility fingerprint, and fail-closed preflight integration.
The brief's own scope boundary **forbids** credential work in the same phase, so it did
not widen row 028; it replaced it.

**This is the twelfth scope amendment.** The conflict was put to the owner with four
options — the roadmap's phase alone, both halves, the ADR-0032 tooling pattern beside
the roadmap's phase, or the brief alone with row 028 left `Planned`. **The owner chose
both halves.**

## Decision

Phase 028 delivers **both**:

1. **The roadmap's own scope.** A local secret store on the Windows Credential Manager,
   satisfying every section of `SECRET_STORE_CONTRACT.md` that binds this phase.
   Recorded in [ADR-0074](0074-the-secret-store-is-the-windows-credential-manager-and-rotation-is-constructed.md).
2. **The environment capability inventory**, as the twelfth scope amendment. Recorded
   in [ADR-0075](0075-native-architecture-is-measured-through-one-adapter-and-a-fingerprint-excludes-what-moves.md).

## Consequences

### This record may cite neither ADR-0070 nor the owner's earlier override

`ROADMAP.md` says of the eleventh amendment:

> **Nothing here answers the granularity question.** It remains Phase 032's, now with
> eleven amendments in front of it, and a twelfth may cite neither this record nor the
> owner's having overridden the refusal once.

Both prohibitions are honoured. Nothing below appeals to ADR-0070, to the series of
amendments, or to the fact that a refusal has been overridden before. The argument is
made from this phase's own facts or not at all.

### ADR-0021's four conditions, restated in full and scored

1. *Nothing is deferred.* **Met.** Row 028's own scope is delivered in full, not
   displaced. Both deferral rows naming Phase 028 — in `SECRET_STORE_CONTRACT.md` and
   in [`../engineering/BOOTSTRAP.md`](../engineering/BOOTSTRAP.md) — are closed, and
   `test_no_document_defers_a_question_to_a_phase_that_has_delivered` is what would have
   caught it had they not been.
2. *No other title changes.* **Met.** No row is retitled, no status other than 028's
   moves, and no band range changes.
3. *Work is not displaced into a phase that owns it.* **Failed.** Phase 030 is
   *Bootstrap Health Check Suite* and Phase 031 is *Offline and Degraded Installation
   Handling*. The capability registry, the required/optional split and the
   degraded-rather-than-blocked classification are all recognisably parts of what those
   two phases were drawn to do.
4. *The two halves need each other.* **Failed.** A secret store and an architecture
   probe are independent. Either could have shipped alone; no gate refused until both
   existed.

**Two of four.** That is the same score the eleventh amendment recorded and better than
the four before it, and **the score is stated rather than argued from** — a count is
not a justification, and this record does not offer it as one.

### What this amendment can say that is its own

**It collides with no phase title.** Phase 030's title is *Bootstrap Health Check
Suite* and Phase 031's is *Offline and Degraded Installation Handling*; neither names
environment capability, architecture, or a compatibility fingerprint. The ninth, tenth
and eleventh amendments each collided with a title — *Supervisor and Watchdog*,
*Operational Metrics Collection*, *Operational Metrics Collection* again. This one
collides with purpose text only, which is the shape of the fourth, fifth and sixth
rather than of the three most recent.

**It overlaps no completed phase.** Phases 030 and 031 are `Planned` and unstarted.

**The collision with Phase 030 is refused rather than rebuilt.** That phase's noun is a
*suite* — the set of preflight checks a long-running process needs. This phase adds
**one** check to a registry that already holds fifteen, and adds it as an entry in
`globin.domain.bootstrap.checks()`, which Phase 021 wrote as a function *precisely so
that later phases add to it instead of rewriting it*. Nothing here proposes the suite,
its scheduling, its periodicity, or its behaviour under a degraded network — all of
which remain Phase 030's and Phase 031's. The observable signal that this refusal
failed would be Phase 030 proposing to rewrite `checks()` rather than extend it.

**Roughly seventy per cent of the brief was already delivered, and that part was
refused rather than rebuilt.** An audit against the brief found the operating system
baseline, the CPython baseline, the `.venv` contract, the installed-distribution check,
the runtime path capability, the redaction of paths, the required/optional statuses,
the fail-closed preflight and the deterministic evidence all present — in
`tools/quality/runtime/`, `tools/quality/drift/`, `tools/quality/lock/` and Phase 021's
bootstrap. **None of it was reimplemented.** `globin.application.environment` produces
no operating-system, interpreter or virtual-environment check at all, and says why: two
verdicts about one fact is the drift
[`../engineering/SOURCE_OF_TRUTH.md`](../engineering/SOURCE_OF_TRUTH.md) exists to
prevent. What was built is the residue nothing owned — the process/native architecture
split, the toolchain probe, and the fingerprint.

### What Phase 032 inherits

Phase 032 is *Environment Consolidation and Phase Gate Review*, and `ROADMAP.md` already
requires it to examine whether Phases 017-032 were drawn at a granularity that describes
the work. **It now has twelve amendments in front of it rather than eleven, and one more
data point for that examination**: this phase's brief and this phase's roadmap row
described two different subjects with no overlap at all, which is a different failure
from a brief that describes work an earlier phase already did. Phase 032 should weigh
that distinction rather than only the count.

A thirteenth amendment inherits nothing from this record, may not cite it, and may not
cite the count above.

## Alternatives Considered

**Deliver the roadmap's phase alone and set the brief aside.** The strongest option on
the roadmap's own terms, and the one that needs no ADR. Declined by the owner. Its cost
was that the brief's genuine residue — the architecture split in particular — has no
owner in the programme at all, so it would have been deferred indefinitely rather than
to a named phase.

**Deliver the brief alone, leaving row 028 `Planned`.** Would have avoided an amendment
entirely, at the price of leaving the store unbuilt while Phase 029 (*Credential
Prompting and Validation Flow*) becomes due immediately after. Declined by the owner.

**Deliver the roadmap's phase, and the residue as tooling under
[ADR-0032](0032-verification-tooling-may-be-added-outside-phase-scope.md).** Considered
seriously and declined for a specific reason rather than a general one: ADR-0032's
fourth condition is that the addition *adds no runtime capability*, and the brief's
central ask — that `globin doctor` and the readiness endpoint know whether this host is
fit — is exactly a runtime capability. An ADR-0032 addition would have had to stay
inside `tools/quality/`, where `tools/quality/runtime/` already lives and where the
package cannot reach it. That is not a smaller version of the brief; it is a different
one.

**Bring Phase 032's granularity review forward to now.** Not offered as an option
because it is not this phase's to schedule, and because a review conducted inside a
phase it would judge is not a review.

## Risks and Trade-offs

**The characteristic failure mode is that Phase 030 arrives and finds its subject
partly built.** The mitigation is the refusal above: one check, added through the
extension point Phase 021 built for it, with the suite, the scheduling and the
degraded-network behaviour untouched. If Phase 030's brief has to argue with
`globin.domain.environment` rather than build on it, this record was wrong.

**A second risk is specific to the secret half and worth naming here rather than in
ADR-0074**: the store exists and holds nothing. `README.md` now says the capability
exists, which lifts the absent-capability rule that had been keeping credential-shaped
names out of the package. The narrower rule that replaces it — `credential`, `password`,
`token`, `keyring` and `apikey` still forbidden, `secret` now permitted — is enforced by
`test_no_module_under_the_package_carries_a_credential_shaped_name`, and it is weaker
than what it replaced. Phase 029 is where that matters.

**A third: the amendment count is now twelve and nothing tests it.** `ROADMAP.md` and
`MEMORY.md` both carry the number in prose, and `MEMORY.md` records that this exact
count drifted once already and was repaired at Phase 025. Both are updated in this
phase's diff; neither is compared against anything.

## References

- [ADR-0021](0021-phase-005-widens-to-include-the-test-foundation.md) — the four conditions, restated and scored above
- [ADR-0032](0032-verification-tooling-may-be-added-outside-phase-scope.md) — the tooling alternative, and the condition that ruled it out
- [ADR-0045](0045-a-platform-capability-is-a-recorded-state-never-a-pass.md) — why an unmeasurable capability degrades rather than blocks
- [ADR-0048](0048-a-secret-lives-outside-the-tree-and-is-redacted-before-a-record-exists.md) — the secret-handling rules this phase implements
- [ADR-0074](0074-the-secret-store-is-the-windows-credential-manager-and-rotation-is-constructed.md) — the store
- [ADR-0075](0075-native-architecture-is-measured-through-one-adapter-and-a-fingerprint-excludes-what-moves.md) — the inventory
- [`../security/SECRET_STORE_CONTRACT.md`](../security/SECRET_STORE_CONTRACT.md) — the contract this phase satisfies
- [`../research/phase_028_sources.md`](../research/phase_028_sources.md) — every platform claim, with its source

## Supersedes

Nothing.

## Superseded By

Nothing.
