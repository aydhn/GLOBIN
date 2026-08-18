# ADR-0082 — Phase 031 widens to deliver the user-scoped secret vault

## Status

Accepted — Phase 031. **Date:** 2026-08-18

## Context

Phase 031's row in [`../../ROADMAP.md`](../../ROADMAP.md) reads *Offline and
Degraded Installation Handling*, and its purpose is one sentence: define behaviour
when the network, GPU or optional native components are unavailable. The brief the
phase was given described a different subject — a secure credential and secret
materialization contract, a user-scoped DPAPI vault, provider selection, and
deterministic secret evidence.

Both were put to the owner with the collision stated, and the owner elected to
deliver both. This record carries the widening.

**Most of the brief was already built**, which is the first thing that had to be
established rather than assumed. Phase 028 delivered the store, the reference and
value types, the one key builder, the 2560-byte fail-closed ceiling and the
constructed rotation; Phase 029 delivered the six-verb command surface, interactive
collection that refuses a pipe before `getpass` is called, and the permission model
with no member meaning *confirmed*; Phase 023 delivered redaction; and
`tools/quality/supply/secrets.py` already scans tracked content for eight
credential shapes. What was genuinely absent was a second mechanism for material
the chosen store **structurally cannot hold**, a way to say which mechanism holds
which reference, and a hand-off reader.

**The measurement that makes the vault necessary is Phase 028's own.**
[`../research/phase_028_sources.md`](../research/phase_028_sources.md) S-11 records
`CRED_MAX_CREDENTIAL_BLOB_SIZE` at 2560 bytes and an RSA-4096 private key in PEM
form at 3324. That is not scope Phase 028 declined; it is scope Phase 028
discovered it could not have.

## Decision

**1. Phase 031 delivers both halves.** The roadmap's titled scope — degraded
operation: a declared component registry, a necessity per component, a posture
folded from what each factory returned, and one new registered check — and, as the
fifteenth scope amendment, the user-scoped secret vault and provider selection.
Row 031's purpose text carries both, and this record carries the cost.

**2. The vault narrowly reverses ADR-0074**, in the shape
[ADR-0078](0078-the-second-lock-reader-is-the-reference-implementation-and-a-cache-is-not-a-source-of-trust.md)
used on ADR-0052 one phase ago. The mechanism is
[ADR-0083](0083-a-second-secret-mechanism-is-admitted-by-arithmetic-and-carries-its-own-integrity-check.md);
what belongs here is that the reversal was taken deliberately and is narrow by
construction rather than by promise.

### Scoring ADR-0021's four conditions

[ADR-0021](0021-phase-005-widens-to-include-the-test-foundation.md) permits an
amendment that can say four things: *nothing displaced, nothing deferred, no phase
owns the work, and the two halves need each other*. This record argues them from
its own evidence and reports the result rather than defending it.

[ADR-0079](0079-phase-030-widens-to-deliver-the-configuration-evidence-surface.md)
closes by naming its own failure signal: *"The observable signal is a fifteenth
amendment citing this record's score as precedent — which this record forbids, in
the same terms ADR-0076 used on it."* Those terms are
[ADR-0076](0076-phase-029-widens-to-deliver-the-dependency-attestation.md)'s:
*"inherits nothing from this record, may not cite it, and may not cite the count
above."* **This record treats the incorporated form as binding in full** rather
than reading the narrower literal wording as a licence, and cites ADR-0079 nowhere
in support below.
[ADR-0070](0070-phase-027-widens-to-deliver-the-loopback-diagnostics-surface.md)
additionally forbids citing the owner's having overridden the roadmap's refusal,
which has now happened five times and is not cited either.

| Condition | Verdict |
|---|---|
| Nothing displaced | **Fails.** Phase 292 *Credential Collection and Persistence Flow* owns storing credentials **by its title**. This is the third title-level collision in the programme, after Phase 263 and Phase 280. |
| Nothing deferred | **Passes.** The titled scope ships whole in this commit, and every document that deferred a question to Phase 031 is reconciled in it. |
| No phase owns the work | **Fails**, and in a way only the seventh amendment has failed before: it overlaps two **`Complete`** phases, 028 and 029. Phases 038 and 039 are touched at the purpose level. |
| The two halves need each other | **Fails.** A degradation posture and a secret vault are independent. Either could have shipped alone, and no gate refuses until both exist. |

**This scores one of four**, which is the joint-worst in the programme and arrives
directly after the only amendment to score four. That sequence is the substance of
the entry rather than an accident of ordering: a test that produced a four and then
a one in consecutive phases is not discriminating between amendments, it is
discriminating between the phases that happened to be adjacent to convenient work.
**That is evidence for the granularity review, and this record contributes it as
evidence rather than as an argument.**

**The collision with Phase 292 is stated rather than refused.** That phase's row
reads "Collect and store credentials securely, never writing them into the
repository". This phase does not *collect* — Phase 029 owns collection and is
complete — but it does *persist*, and calling that something else would be a naming
exercise. Phase 292 inherits this vault.

**The two halves do not need each other, and two bridges that would connect them
are refused rather than left unmentioned.**

- *"A vault makes credentials available when the network is down."* False. GLOBIN
  reaches no venue: `required_references()` is empty and `VerificationState` has no
  member meaning confirmed, so there is no offline path a vault unblocks because
  there is no online path.
- *"The vault is the fallback when the Credential Manager is unreachable."*
  **Forbidden.** [`../security/SECRET_STORE_CONTRACT.md`](../security/SECRET_STORE_CONTRACT.md)
  §3 requires a typed refusal and names the prohibition: "never a quiet fall back
  to somewhere less protected". No code path in this phase catches
  `NO_CREDENTIAL_SET` and answers from a file, and
  `tests/unit/test_secret_environment.py` asserts the absence as a call count
  rather than as a returned fault.

**The granularity question remains Phase 032's, now with fifteen amendments in
front of it**, and this record answers no part of it.

## Consequences

**What this costs.** `ROADMAP.md` carries a fifteenth entry in its *Scope
amendments* block, and the cost of the programme's fixity is now visible fifteen
times in thirty-one phases. Phase 292 arrives to find its subject partly built, and
this record is what it will read.

**What is now prohibited that a contributor might reasonably want.** A fallback
edge between the two secret mechanisms — the obvious convenience, and the thing §3
forbids by name. A vault entry for material that fits the store's ceiling: the two
are disjoint by arithmetic and a value belonging to both would make "where is this
secret" unanswerable.

**What enforcement exists.** `tests/unit/test_secret_environment.py` counts calls
to prove no second mechanism is consulted;
`tests/architecture/test_credential_discipline.py` holds `crypt32` to one loader;
`tests/architecture/test_degradation_discipline.py` makes the component registry
complete in both directions; and `tests/contract/test_roadmap_contract.py` compares
row 031's status against the delivered frontier.

## Alternatives Considered

**Deliver the roadmap's phase alone and set the brief aside.** The strongest option
on the roadmap's own terms and the one that needs no ADR. Declined by the owner,
with the score above stated in advance. Its cost was that the genuine residue — key
material the chosen store cannot hold — has no owner in the programme until Phase
292, which is 261 phases away.

**Deliver the brief alone, leaving row 031 `Planned`.** Would have avoided an
amendment, at the price of leaving degraded operation unowned while four documents
went on deferring to a phase that had shipped something else. Declined.

**Deliver the residue as tooling under
[ADR-0032](0032-verification-tooling-may-be-added-outside-phase-scope.md).**
Declined for the specific reason Phases 028 and 029 declined it: that record's
fourth condition is that the addition *adds no runtime capability*, and both halves
here are runtime capabilities.

**Retitle Phase 031 to the brief's subject.** Rejected. Band ranges and the
sixteen-phase width are fixed, and a retitling would leave degraded operation with
no row at all — which is worse than a widening, because a widening is visible and a
missing subject is not.

## Risks and Trade-offs

**The characteristic failure mode is that the amendment test has stopped
discriminating.** Fifteen amendments in thirty-one phases, scoring between one and
four with no apparent relation to how well the work fitted, is a test being applied
rather than a test deciding anything. **The observable signal is Phase 032 finding
that it cannot conduct the granularity review without first deciding whether the
test is worth keeping.**

**The second characteristic failure is that Phase 292 arrives and finds its subject
built.** There is no mitigation beyond the boundary stated above, because the owner
accepted the collision knowingly. If Phase 292's brief has to argue with
`globin/adapters/secret_vault.py`, this record was wrong and said so in advance.

**Confidence.** High that the two halves are independent — that is a structural
fact rather than a judgement. High on the collision with Phase 292. Moderate on the
claim that the vault is narrow enough not to displace ADR-0074's *decision*: it
rests on the admission rule staying arithmetic, which
`tests/unit/test_secret_vault.py` checks but which a later phase could widen with a
one-line edit.

A sixteenth amendment inherits nothing from this record, may not cite it, may not
cite the count above, and may not cite the fact that a one-of-four amendment was
taken.

## References

- [ADR-0021](0021-phase-005-widens-to-include-the-test-foundation.md) — the four conditions
- [ADR-0074](0074-the-secret-store-is-the-windows-credential-manager-and-rotation-is-constructed.md) — the store, and the decline this phase narrowly reverses
- [ADR-0076](0076-phase-029-widens-to-deliver-the-dependency-attestation.md) — the prohibition incorporated above, and the boundary it drew for this phase
- [ADR-0083](0083-a-second-secret-mechanism-is-admitted-by-arithmetic-and-carries-its-own-integrity-check.md) — the vault's own decisions
- [`../research/phase_031_sources.md`](../research/phase_031_sources.md) — every platform claim this phase rests on
- [`../engineering/DEGRADED_OPERATION.md`](../engineering/DEGRADED_OPERATION.md) — the titled half

## Supersedes

Nothing.

## Superseded By

Nothing yet.
