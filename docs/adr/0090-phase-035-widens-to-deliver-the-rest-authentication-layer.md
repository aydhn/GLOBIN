# ADR-0090 — Phase 035 widens to deliver the REST authentication layer

## Status

Accepted — Phase 035. **Date:** 2026-08-19

## Context

`ROADMAP.md` row 035 reads *Environment Classification Model*, with the purpose
*"Model production, testnet, demo and internal simulation as distinct classes with
distinct guarantees."*

The phase brief asked instead for capability-gated REST authentication and
deterministic request signing — which is row **038**, *Request Signing and
Authentication*.

**The repository names Phase 038 for this work in five places**, which is what
made the conflict impossible to miss rather than a matter of interpretation:

- [`domain/rest.py`](../../src/globin/domain/rest.py) —
  `RequestSecurityIntent`: *"Phase 038 implements what the two authenticated
  members mean on the wire. Nothing here signs anything."*
- The same module's `percent_encode`: *"Phase 038's signer computes a signature
  over the exact query string this module renders."*
- [`domain/secrets.py`](../../src/globin/domain/secrets.py) — *"which key type is
  used (Phases 029 and 038), and what an environment* is *(Phase 035)."*
- [`degradation-contract.toml`](../engineering/degradation-contract.toml) —
  `advapi32`: *"the moment Phase 038 registers one the same declaration begins to
  refuse a start."*
- [`rest-transport.toml`](../engineering/rest-transport.toml) —
  `request_signing = false`, bound by a contract test.

**Row 035's own subject had already been largely delivered.** The seventeenth
amendment (ADR-0086) records that Phase 033 took *"production, demo and testnet as
distinct kinds rather than a boolean"*, naming row 035 as one of four rows it
displaced; the eighteenth (ADR-0088) names row 035 again. What survived is a
remainder the code itself identifies:
[`identifiers.py`](../../src/globin/domain/identifiers.py) says *"Phase 035 models
the classes and their guarantees"*, and
[`config/profiles/paper.toml`](../../config/profiles/paper.toml) says *"What an
environment* is*, and how production, testnet and demo differ, is Phase 035."*

The registry classifies only environments the **venue** publishes. It has no row —
and structurally cannot have one — for `paper`, GLOBIN's own internal simulation
and its `DEFAULT_PROFILE`.

**The operator was shown the conflict before any code was written**, with three
courses and their costs, and chose to deliver both halves.

## Decision

**Phase 035 delivers row 035's remainder and the REST authentication layer, as the
nineteenth scope amendment.**

The titled half: four environment classes with seven guarantees each, declared in
[`environment-classes.toml`](../engineering/environment-classes.toml) with
provenance, read by one adapter, and holding the class the registry cannot express.

The amendment: capability-gated authentication over HMAC, RSA and Ed25519,
signing the exact characters that reach the wire, with eight fail-closed gates and
no algorithm fallback. [ADR-0091](0091-authentication-is-capability-driven-and-product-scoped.md)
carries the algorithm-selection rule.

**Row 038 is not rewritten.** ADR-0088 rewrote rows 034 and 045 and recorded that
as *"the first exception … recorded as an exception rather than as precedent"*.
This record takes that seriously: row 038 keeps its text, loses work, and is
recorded as displaced in the ledger like the eight amendments before the
eighteenth.

**Three things this amendment does not do**, each of which would have been
defensible:

*It does not fill `required_credentials()`.* That function is empty by derivation
and its own docstring names Phase 038 as the filler. Filling it would flip
`advapi32` from *not applicable* to *required*, and a host without an enrolled
credential — which is every host, including CI — would stop starting. A credential
is required for a signed **request**, not for a **start**. Phase 039 owns it.

*It does not add an exit code.* 26 stays free, as it has since Phase 030.

*It does not flip `request_signing` in `rest-transport.toml`.* The first draft did,
and the transport's own contract test caught it. That table says what **the
transport** will not do, and the transport still has no signer, no key and no
credential — `_exchange` renders exactly the request it was handed. Signing happens
a layer up and arrives indistinguishable from any other request.

## Consequences

**The amendment scores two of ADR-0021's four conditions.**

| Condition | Verdict | Why |
|---|---|---|
| Nothing displaced | **FAILED** | Row 038 loses its whole subject. Rows 036 and 037 lose nothing further than the seventeenth already took |
| Nothing deferred | **MET** | Both halves ship in one commit; nothing planned for row 035 is pushed out |
| No phase owns the work | **FAILED** | Row 038 owns request signing **by title**, and the package names it in five places |
| The two halves need each other | **MET** | See below — this is the one that did the deciding |

**The fourth condition is met more strongly here than in any prior amendment, and
that is the substance of this record rather than a defence of it.**
`accepts_credential` is **gate 1** of the authentication admission, checked before
the registry is consulted, before a credential is looked up, and before a signer is
chosen. An environment GLOBIN simulates reaches no venue, so there is nothing a
credential could mean there — and no existing type could say so. The registry
cannot: a registry of venue facts has nowhere to put an environment the venue has
never heard of.

Without the classification, *"do not sign for paper"* is a rule somebody has to
remember. With it, a `paper` request is refused with **no credential having been
reached for**, which a test asserts using a secret store that fails if anything
asks it for anything.

**What becomes harder.** Row 038 arrives with its subject already built, which is
the same position row 045 was left in by the eighteenth amendment. A reader
planning it will find signing done and permission verification, weight accounting
and the operation register still open.

**What is now prohibited.** No fallback between signature algorithms, in any
direction, under any circumstance — including a degraded host missing
`cryptography`, where the tempting fallback to HMAC would move an operator onto the
algorithm the venue calls deprecated. Enforced by `algorithm_for()` having no
default branch, by `UnavailableAsymmetricSigner` raising rather than substituting,
and by [`test_signing_discipline.py`](../../tests/architecture/test_signing_discipline.py).

**A new runtime dependency.** `cryptography` is the tenth, the first adopted for a
*security* capability, and the seventh absent-safe component. Three distributions,
measured before acceptance. Its written review is in
[`dependency-reviews.toml`](../engineering/dependency-reviews.toml).

## Alternatives Considered

**Deliver only row 035 as written, and defer signing to row 038.** The option that
respects the roadmap exactly. Its cost is that row 035's remainder is small — one
class the registry cannot hold, and a mapping — and would have shipped as a model
with no consumer, which is how a declared document quietly becomes wrong. Refused
by the operator after the conflict was surfaced.

**Deliver signing alone and rewrite rows 035 and 038.** Rejected because the
granularity review reserved rewriting for Phase 048 and ADR-0088 recorded its own
rewrite as an exception rather than a precedent. Doing it a second time, three
phases later, would make the exception a habit. It would also have discarded the
one thing that makes this amendment's fourth condition true.

**Fill `required_credentials()` and make the phase complete on its own terms.**
Rejected on evidence rather than caution: the function's docstring already records
what happens — *"declaring one here would make `bootstrap check` refuse on every
clean host, including the one CI builds, which could only be satisfied by
manufacturing a credential to meet a requirement nothing has established."* The
requirement still is not established; nothing runs at start-up that uses a
credential.

**Model the environment classes inside `binance-api-reality.toml`.** Rejected
because it cannot hold `paper` without recording a claim about Binance that
Binance does not make. Two documents answering two questions is the honest shape.

## Risks and Trade-offs

**The characteristic failure mode is that the amendment ledger stops being read.**
Nineteen entries is a long list, and a reader who skims it learns that amendments
are routine rather than that each was argued. The signal is an amendment whose
record cites the count rather than the conditions; ADR-0082 forbade exactly that
of its successor, and this record cites neither a prior score nor the total in its
own argument.

**The second is that row 038 is planned as though it were empty.** A reader
reaching it will find the signing subject delivered and may either duplicate it or
skip the row entirely. The ROADMAP entry names row 038 explicitly, which is the
mitigation the eight amendments before the eighteenth used and which ADR-0088
judged insufficient once — for a row whose *whole title* had gone. Row 038's title
covers *authentication* broadly, and permission verification remains open under it,
so a rewrite would be less accurate than the displacement note.

**The third is specific to the dependency.** `cryptography` carries a compiled Rust
extension, and an interpreter bump with no wheel would leave two of three
algorithms unavailable. The mitigation is measured rather than hoped: the wheel is
`cp311-abi3`, serving every CPython from 3.11, so both interpreters CI tests
install the same artefact. The observable signal is
`component.library.cryptography` reporting absent on a host that has `.venv`.

## References

- [ADR-0021](0021-phase-005-widens-to-include-the-test-foundation.md) — the four
  conditions this record scores itself against
- [ADR-0086](0086-phase-033-widens-to-deliver-the-binance-api-reality-registry.md)
  — the seventeenth amendment, which first displaced row 035
- [ADR-0088](0088-phase-034-widens-to-deliver-the-rest-transport-substrate.md) —
  the eighteenth, and the transport this layer sits on
- [ADR-0091](0091-authentication-is-capability-driven-and-product-scoped.md) — the
  algorithm-selection rule
- [ADR-0006](0006-product-and-environment-capability-matrix.md) — *never downgrade
  an unmapped combination to production*
- [`ENVIRONMENT_CLASSES.md`](../engineering/ENVIRONMENT_CLASSES.md),
  [`REST_AUTHENTICATION.md`](../engineering/REST_AUTHENTICATION.md)
- [`phase_035_sources.md`](../research/phase_035_sources.md)

## Supersedes

None.

## Superseded By

None.
