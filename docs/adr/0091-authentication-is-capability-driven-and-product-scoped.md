# ADR-0091 — Authentication is capability-driven and product-scoped, and no algorithm is a fallback

## Status

Accepted — Phase 035. **Date:** 2026-08-19

## Context

Binance publishes eight product families and documents each separately. GLOBIN
reads only Spot today: its REST surface is the one the registry records as
`supported`, and the other twelve families' REST surfaces are `unknown` because
their documentation is a client-rendered application with no admissible route —
`docs/SOURCE_POLICY.md` forbids both scraping it and accepting a generated summary
in its place.

The pressure is that **the Spot contract is the only one anybody can read, and it
is therefore the one that would get generalised.** A signing layer written from
Spot alone naturally produces one `sign()` function, one payload rule and one key
type mapping, all of them correct for Spot and none of them checked against
anything else. When a derivatives adapter arrives at Phase 071, the cheapest thing
to do is reuse them.

That failure is silent in exactly the way this repository's outcome model exists to
prevent. A signature computed under the wrong contract is not rejected by any check
here; it is rejected by the venue, with `-1022 INVALID_SIGNATURE`, at the point an
order was being placed.

Three further facts from `docs/research/phase_035_sources.md` sharpen it:

- **HMAC is documented deprecated** (S-04), in a document `rest-api.md` links to by
  name and which neither `rest-api.md` nor the changelog restates. So the algorithm
  a naive default would pick is the one the venue is asking people to leave.
- **The venue's own Ed25519 worked examples are RSA output** (S-05) — one decoding
  to 256 bytes and byte-identical to the RSA section's, the other not valid base64
  at all. A layer that copied an example rather than reading the normative text
  would have shipped an "Ed25519 signer" that reproduced RSA behaviour.
- **PSS is explicitly unsupported** (S-06), and is one argument away from PKCS#1
  v1.5 in the chosen library's API, producing signatures of identical length.

Phase 033 already recorded `key_types` per endpoint. Nothing consumed it.

## Decision

**Which algorithm may sign a request is read from the capability registry, scoped
to one product and one environment, and never inferred from another product.**

Four rules, each enforced rather than documented.

**1. Selection is a lookup.** `EndpointRecord.key_types` is carried through
`ResolvedEndpoint` and compared against the configured credential. There is no
per-product table in the authentication layer, no `if family == …`, and
[`test_api_reality_discipline.py`](../../tests/architecture/test_api_reality_discipline.py)
still fails if a venue host is spelled in a module.

**2. There is no fallback algorithm, in any direction.**
`algorithm_for()` and `encoding_for()` are total over their enumerations and have
**no default branch**. A key type with no mapped algorithm is a refusal. A host
whose signer for an algorithm is unavailable produces
`AuthStatus.SIGNER_UNAVAILABLE` naming the missing library — never a substitution.
`UnavailableAsymmetricSigner.sign` raises, and raises *before* reading any
material.

**3. One product's contract may not stand in for another's.**
`SigningProfile` carries the placement, encoding and parameter names per surface,
and `spot_profile()` is a function rather than a row in a shared table. A second
product with a documented REST surface adds a second function and a row in
`auth-contract.toml`; it does not add a branch.

**4. A signature's case is never normalised.** RSA and Ed25519 signatures are
documented case-sensitive and HMAC's is not, so the only safe rule is to transform
nothing. No `upper()` or `lower()` exists anywhere on the signing path, and
`GeneratedSignature` has no method that would apply one.

Two absences are asserted rather than trusted, on the same principle
`test_rest_contract.py` uses for `CERT_NONE`: **a validator can only refuse what
reaches it, so an absence is stronger than a branch.** `PSS` and `MGF1` appear
nowhere in the package as code, and `cryptography` is imported by exactly one
module, checked in both directions by
[`test_signing_discipline.py`](../../tests/architecture/test_signing_discipline.py).

**What this does not cover.** It says nothing about *whether* a key is entitled to
an operation — that is Phase 039's permission model, and
`VerificationState` still has no member meaning *confirmed*. It says nothing about
request weight (Phase 041), rate limiting (042), retry (043) or error-code mapping
(044).

## Consequences

**A product whose signing contract nobody has read cannot be signed for.** Twelve
of thirteen recorded families refuse at the endpoint gate today, before
authentication is consulted at all. That is the intended outcome and it is the
expensive one: adding derivatives support requires an admissible source for their
documentation, which does not currently exist.

**A degraded host loses the recommended algorithm rather than authentication.**
HMAC is `hmac` and `hashlib`, so a host without `cryptography` still signs — and
refuses an RSA or Ed25519 request with the library named. This is the one place in
this repository where an absent-safe component **refuses** rather than recording an
absence, and the asymmetry is deliberate: everywhere else a missing library means a
measurement is not taken, and here it would mean a different algorithm is used.

**A key type added at the venue is a registry edit and a signer, in that order.**
`ApiKeyType` is an enumeration rather than data — unlike `ProductFamily` and
`EnvironmentName`, which are validated strings — because these are cryptographic
algorithms GLOBIN must implement rather than names a venue invents. A fourth
requires code, which is the correct cost.

**An operator with no `auth.key_type` configured gets a refusal, not a default.**
That is a worse first-run experience than a default would give, and it is the
point: the obvious default is the deprecated algorithm, applied to whatever secret
happened to be enrolled.

## Alternatives Considered

**One signer with an algorithm parameter, and a default.** Simpler, and it is what
most client libraries do. Rejected because the default is where the failure lives:
every such library defaults to HMAC, which is now the deprecated type, and a caller
who mis-configured a key type would get a working request signed with the wrong
credential rather than a refusal.

**Fall back to HMAC when `cryptography` is absent.** Rejected explicitly rather
than not considered. It reads as resilience and is a security regression: it uses a
key the operator enrolled for a different purpose, on an algorithm the venue
documents as deprecated, on a host the operator believes is running Ed25519. The
whole absent-safe pattern in this repository is about *reporting* a lost
capability, and this is the case where reporting and substituting diverge.

**Derive the algorithm from the key material itself** — parse the PEM, see what it
is, sign accordingly. Rejected because it removes the mismatch check that catches
the realistic mistake. An Ed25519 key and an RSA key both arrive as
PKCS#8 blocks with the same armour line and are indistinguishable by eye; a credential filed
under the wrong type is exactly what the declared-versus-actual comparison finds,
and inferring would make it unfindable.

**Use the venue's published Ed25519 vectors as known-answer tests.** Rejected on
measurement: they are RSA output. The normative text supplies the contract and
RFC 8032 supplies the vectors, which is the arrangement `SOURCE_POLICY.md`'s tiers
already imply — upstream documentation is authoritative for the thing it documents,
and the thing RFC 8032 documents is Ed25519.

**Take a Binance SDK's signing code as the reference.** Rejected under
`SOURCE_POLICY.md`, and S-05 is the argument rather than the rule: a reader who
trusted the venue's own documentation would have been wrong here, and a reader who
trusted an SDK would have had no way to notice.

## Risks and Trade-offs

**The characteristic failure mode is over-refusal.** A registry row that is stale
or conservative makes GLOBIN decline a request the venue would have accepted, and
the failure looks like a bug in this layer rather than in the document.
The observable signal is `CREDENTIAL_TYPE_MISMATCH` or `ENDPOINT_UNRESOLVED` on a
surface an operator has used successfully by other means — and the remedy is a
registry edit with a source, not a change here.

**The second is that "no fallback" is only as strong as the enumeration.** Both
mapping functions raise on an unmapped member, but a member added to
`SignatureAlgorithm` without a corresponding entry would fail at runtime rather than
at import. A contract test compares the two mappings over every member in both
directions, which catches it in the suite rather than in a request.

**The third is confidence in the deprecation.** HMAC is recorded `deprecated` on
the strength of one sentence in one document. If Binance withdrew it the status
would be wrong in the *safe* direction — an operator warned about something still
supported. The signal is a changelog entry, and the ingestion cadence is what would
surface it.

## References

- [ADR-0006](0006-product-and-environment-capability-matrix.md) — never assume one
  universal test environment, and never downgrade an unmapped combination
- [ADR-0087](0087-the-api-reality-registry-is-declared-with-provenance-and-drift-is-measured-in-two-regimes.md)
  — the registry this reads
- [ADR-0089](0089-an-unknown-outcome-is-preserved-and-a-second-module-may-reach-a-socket.md)
  — the transport, and the socket rule this does not relax
- [ADR-0090](0090-phase-035-widens-to-deliver-the-rest-authentication-layer.md) —
  the amendment that scheduled this
- [ADR-0045](0045-a-platform-capability-is-a-recorded-state-never-a-pass.md) —
  absence is a recorded state
- [`REST_AUTHENTICATION.md`](../engineering/REST_AUTHENTICATION.md),
  [`auth-contract.toml`](../engineering/auth-contract.toml)
- [`phase_035_sources.md`](../research/phase_035_sources.md) — S-04, S-05 and S-06
  are the three findings this record rests on

## Supersedes

None.

## Superseded By

None.
