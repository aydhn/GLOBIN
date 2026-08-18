# ADR-0076 — Phase 029 widens to deliver the dependency attestation

## Status

Accepted — Phase 029.

**Date:** 2026-08-18

## Context

`ROADMAP.md` row 029 is *Credential Prompting and Validation Flow*: "Define interactive
credential collection, format validation and permission verification before use." That
scope was well prepared. Phase 015 wrote the rules
([ADR-0048](0048-a-secret-lives-outside-the-tree-and-is-redacted-before-a-record-exists.md)),
Phase 020 measured what Windows offers, Phase 021 cut the `SecretProbe` seam, and Phase 028
built the store and left `StoreBackedSecrets.required` empty with a comment naming this
phase.

The owner asked for something else as well: reproducible dependency environment
materialization, PEP 751 interoperability, hash-verified wheel-first installation,
ABI/platform compatibility, dependency-drift gates and deterministic dependency evidence.

**This is the thirteenth scope amendment.** The conflict was put to the owner with four
options — the roadmap's phase alone, both halves, the ADR-0032 tooling pattern beside the
roadmap's phase, or the brief alone with row 029 left `Planned`. **The owner chose both
halves.**

Two further boundaries were put to the owner separately and are recorded here because they
are what make condition 3 below score as badly as it does. The brief's offline and
clean-room sections were identified as reproducing Phase 031's *title* and reaching into
Phase 032's subject; the owner was shown that and **chose to include them**. And the
`packaging` question — the brief asks for `packaging.tags` where ADR-0052 decision 9
records a deliberate refusal to adopt it — was put as a three-way choice, and the owner
**chose to adopt it as a runtime dependency**.

## Decision

Phase 029 delivers **both**:

1. **The roadmap's own scope.** Interactive credential collection, structural format
   validation, and permission verification before use. Recorded in
   [ADR-0077](0077-a-credential-is-collected-at-a-console-and-a-permission-is-declared-rather-than-verified.md).
2. **The dependency attestation**, as the thirteenth scope amendment. Recorded in
   [ADR-0078](0078-the-second-lock-reader-is-the-reference-implementation-and-a-cache-is-not-a-source-of-trust.md).

## Consequences

### ADR-0021's four conditions, restated in full and scored

1. *Nothing is deferred.* **Met.** Row 029's own scope is delivered in full, not displaced.
   The credential flow exists end to end: a console entry that refuses a pipe, a structural
   validator, a store write, a rotation that reuses Phase 028's four-step ordering
   unchanged, a permission model, an eighteenth bootstrap check and a six-verb command
   group matching `SECRET_STORE_CONTRACT.md` section 5 exactly.
2. *No other title changes.* **Met.** No row is retitled, no status other than 029's moves,
   and no band range changes.
3. *Work is not displaced into a phase that owns it.* **Failed, and failed worse than in
   any previous amendment.** Phase 031 is *Offline and Degraded Installation Handling* and
   the offline materialization gate reproduces that **title**, not merely its purpose text.
   Phase 030 is *Bootstrap Health Check Suite* and this phase adds a check to the registry
   Phase 021 built for the purpose. Phase 032 is *Environment Consolidation and Phase Gate
   Review* and the clean-room harness reaches into what that phase was drawn to certify.
   Phase 020 is **complete**, and its subject — lock governance — is the one this
   amendment extends.
4. *The two halves need each other.* **Failed.** A credential flow and a dependency
   attestation are independent. Either could have shipped alone; no gate refused until both
   existed.

**Two of four**, and the count is stated rather than argued from. What distinguishes this
record from a better-scoring one is not worth softening: **condition 3 fails against three
`Planned` phases and one completed one**, which is the widest displacement any amendment
in this programme has recorded. The owner was shown that before choosing, and that is the
reason — not a mitigation of it.

### What this amendment can say that is its own

**The credential half was genuinely prepared, and the preparation was consumed rather than
bypassed.** `StoreBackedSecrets.required` was left empty at Phase 028 with a comment naming
this phase; it is now fed from `globin.domain.entitlements.required_references`. The
`SecretProbe` seam Phase 021 cut is joined by a second probe rather than widened.
`WindowsCredentialStore.inventory` returned empty with a docstring promising "the
declaration resolved one reference at a time through `resolve`", and that is now literally
what it does.

**Roughly two thirds of the dependency brief was already delivered, and that part was
refused rather than rebuilt.** An audit found PEP 751 parsing, hash recomputation, artefact
host checking, PEP 425 tag matching, four-register reconciliation and lock-first
installation all present in `tools/quality/lock/`, `tools/quality/wheels/`,
`tools/quality/drift/` and `scripts/bootstrap.ps1`. **None of it was reimplemented.**
`tools/quality/wheels/plan.py` remains the only answer to the declared-target question and
was not touched. What was built is the residue nothing owned: a *running* GLOBIN could not
see a dependency version at all, and `ReadinessReason.DEPENDENCY_UNREADY` had been declared
at Phase 027 with **no caller anywhere**.

**The `packaging` adoption reverses a recorded decision, and the reversal is narrow.**
ADR-0052 decision 9 says of Phase 018: "No dependency was added — `urllib.request` and
`re`, not `packaging`." That was right for the question Phase 018 had. This phase needs a
*running* GLOBIN to evaluate PEP 508 markers and compare PEP 440 versions, which the Phase
018 subset refuses **by name** rather than by omission. The hand-written matcher stays and
is still the only one in `tools/`.

### What Phase 030 and Phase 031 inherit, and what is refused

**Phase 030's collision is refused rather than rebuilt.** That phase's noun is a *suite*.
This phase adds **one** check to a registry that already held seventeen, through
`globin.domain.bootstrap.checks()`, which Phase 021 wrote as a function precisely so later
phases add to it. Nothing here proposes the suite, its scheduling, its periodicity, or its
behaviour under a degraded network. **The observable signal that this refusal failed** is
Phase 030 proposing to rewrite `checks()` rather than extend it.

**Phase 031's collision is not refused, and pretending otherwise would be dishonest.** The
offline materialization gate answers "could this environment be built from local bytes",
which is a substantial part of what that phase was drawn to do. What is left to it is the
*behaviour* under degradation — what a running GLOBIN does when an optional component is
missing, how it reports a partial capability, and what it refuses to start without. This
phase answers only a verdict about a lock and a directory. **The observable signal that
this boundary was drawn wrong** is Phase 031 finding it must argue with
`tools/quality/materialize/` rather than build on it.

**Phase 032 inherits thirteen amendments rather than twelve**, and one more data point: this
phase's brief and its roadmap row described two different subjects, and the owner elected to
deliver both after being shown the cost. That is the second consecutive phase in which the
brief and the row did not overlap at all.

A fourteenth amendment inherits nothing from this record, may not cite it, and may not cite
the count above.

## Alternatives Considered

**Deliver the roadmap's phase alone and set the brief aside.** The strongest option on the
roadmap's own terms and the one that needs no ADR. Declined by the owner. Its cost was that
the genuine residue — a runtime blind to its own dependency versions — has no owner in the
programme at all.

**Deliver the brief alone, leaving row 029 `Planned`.** Would have avoided an amendment, at
the price of leaving the credential flow unbuilt while Phase 030's preflight suite becomes
due immediately after. Declined by the owner.

**Deliver the roadmap's phase, and the residue as tooling under
[ADR-0032](0032-verification-tooling-may-be-added-outside-phase-scope.md).** Considered and
declined for the same specific reason Phase 028 declined it: ADR-0032's fourth condition is
that the addition *adds no runtime capability*, and the central ask — that a running GLOBIN
know whether its environment matches its lock — is exactly a runtime capability.

**Refuse the offline and clean-room halves and deliver only the runtime inventory.** This
was the recommendation put to the owner, on the grounds that Phase 031's title covers them.
Declined by the owner, with the collision stated in advance.

## Risks and Trade-offs

**The characteristic failure mode is that Phase 031 arrives and finds its subject largely
built.** There is no mitigation offered for this beyond the boundary stated above, because
the owner accepted the collision knowingly. If Phase 031's brief has to argue with this
code, this record was wrong and said so in advance.

**A second risk is that `packaging` is now load-bearing with no absent-safe factory.** Every
other runtime dependency has one; this does not, because a dependency inventory that cannot
compare versions is not a degraded inventory but the defect this phase removes. The
mitigation is containment — `tests/architecture/test_packaging_discipline.py` confines it to
two modules — and the observation that `pytest` itself requires it, so it is present
wherever the suite runs. `.github/workflows/quality.yml` now pins it explicitly so that
availability is a declaration rather than a circumstance.

**A third: the amendment count is now thirteen and nothing tests it.** `ROADMAP.md` and
`MEMORY.md` both carry the number in prose, and `MEMORY.md` records that this exact count
drifted once already and was repaired at Phase 025. Both are updated in this phase's diff;
neither is compared against anything.

## References

- [ADR-0021](0021-phase-005-widens-to-include-the-test-foundation.md) — the four conditions, restated and scored above
- [ADR-0032](0032-verification-tooling-may-be-added-outside-phase-scope.md) — the tooling alternative, and the condition that ruled it out
- [ADR-0045](0045-a-platform-capability-is-a-recorded-state-never-a-pass.md) — why a verification state has no confirmed member
- [ADR-0052](0052-wheel-availability-is-a-recorded-survey-whose-verdict-is-recomputed.md) — decision 9, which this phase reverses narrowly
- [ADR-0054](0054-the-toolchain-is-locked-with-pep-751-and-the-verdict-is-recomputed.md) — the lock governance this phase extends and does not replace
- [ADR-0077](0077-a-credential-is-collected-at-a-console-and-a-permission-is-declared-rather-than-verified.md) — the credential flow
- [ADR-0078](0078-the-second-lock-reader-is-the-reference-implementation-and-a-cache-is-not-a-source-of-trust.md) — the dependency attestation
- [`../research/phase_029_sources.md`](../research/phase_029_sources.md) — every platform and specification claim, with its source

## Supersedes

Nothing.

## Superseded By

Nothing.
