# ADR-0087 — The API reality registry is declared with provenance, and drift is measured in two regimes

## Status

Accepted — Phase 033. **Date:** 2026-08-19

## Context

[ADR-0086](0086-phase-033-widens-to-deliver-the-binance-api-reality-registry.md)
widened Phase 033 to deliver a registry of what Binance exposes. This record
carries the technical decisions that widening required.

Two facts shaped every one of them.

**The first is that documentation is prose.** Binance's REST, WebSocket, FIX and
demo-mode documents are Markdown written for humans. A base URL sits in a table
in one document and a sentence in another; an authentication restriction is a
clause. Extracting capability rows from that automatically produces answers that
look typed and are guesses. Meanwhile `sbe/schemas/sbe_schema_lifecycle_prod.json`
is a machine-readable record of which schema is current, which are deprecated and
which are retired, with dates — and Binance's own changelog treats it as
authoritative, recording that *"The SBE lifecycle for Production has been updated
to reflect this change."* The two kinds of source cannot honestly be read the same
way.

**The second is that this repository has never made an outbound connection.**
`tests/architecture/test_library_discipline.py` names one module that may reach a
socket, `globin.adapters.diagnostics_http`, and that module *binds* rather than
connects — the address is a `LoopbackAddress` that cannot hold anything
`ipaddress` does not call loopback. Nothing in `src/globin` imports `urllib`,
`httpx`, `requests` or `http.client`. A registry that refreshes itself from the
internet has to decide where that connection lives before it can be written.

## Decision

### 1. The registry is one declared document, and provenance is structural

`docs/engineering/binance-api-reality.toml` is the single place a Binance fact is
written down. It follows the shape every contract in this repository uses — a
`schema` number refused if unrecognised, a `[target]` table, arrays of tables — and
`globin.adapters.api_reality` is the only reader.

Every record that asserts a capability carries a source. This is enforced by
`__post_init__` rather than by review: a record without a canonical location, an
authority and an access date cannot be constructed. Provenance is not metadata
attached to the interesting part; a claim about a venue with no source is not a
weaker claim, it is not a claim.

The domain holds the types and the reader lives in the adapters layer, because
`dependency-rules.toml` lists `tomllib` among the I/O-capable modules and the
domain may import none of them.

### 2. Six status words, on one axis, and it is not `CapabilityStatus`

`SurfaceStatus` has exactly six members: `SUPPORTED`, `UNSUPPORTED`, `UNKNOWN`,
`DEPRECATED`, `ANNOUNCED`, `RESTRICTED`.

The axis is *what do the official documents say about our ability to use this
surface*. `SUPPORTED` is documented yes; `RESTRICTED` is documented yes subject to
an eligibility, key-type or permission condition; `UNSUPPORTED` is documented no;
`DEPRECATED` is documented yes-and-going-away; `ANNOUNCED` is documented
not-yet-and-scheduled; `UNKNOWN` is the documents not saying. All six answer the
same question, which is what makes them one enumeration rather than two.

**It deliberately does not reuse `CapabilityStatus`** from
`globin.domain.environment`, and the house convention is that reuse beats forking,
so the divergence needs its reason. `CapabilityStatus` answers *what did we measure
about this host*. Its `DEGRADED` and `NOT_APPLICABLE` have no meaning for a remote
venue's documented contract — a documented surface is not usable-but-worse, and
the question always arises. Three of these six have no meaning for a host: a CPU
architecture is not deprecated and a filesystem is not announced. The two share
three spellings and no subject, and merging them would produce one enumeration
where half the members are unreachable from either caller.

`UNKNOWN` is never a synonym for no, exactly as `CapabilityStatus` states for its
own member. The distinction is the point of the phase: *not documented* and
*documented absent* are different facts, and a registry that flattened them would
let Phase 038 infer support from silence.

### 3. `OBSERVED` exists and nothing can produce it

`EvidenceKind` has three members: `DOCUMENTED`, `INFERRED`, `OBSERVED`.

GLOBIN has never contacted Binance. No record in this repository may therefore
claim to have observed anything, and `tests/contract/test_api_reality_contract.py`
asserts that no committed row carries `OBSERVED`. The member exists because Phases
045 onward will have a transport and will be able to record what a venue actually
did, and adding it then would mean re-versioning the schema; it is unproducible
now because there is nothing to produce it.

This is the same shape as `VerificationState` having no member meaning *confirmed*
— there, the absence of the member is what makes the rule structural. Here the
member is present and the *test* is what makes it structural, because the member
has a future producer and the absent one did not.

### 4. Drift is measured in two regimes, and the split is the deliverable

| Source kind | Detection | Verdict on change |
|---|---|---|
| Structured (`sbe_schema_lifecycle_prod.json` and its three siblings) | **Field-level.** Parse it; compare the latest, deprecated and retired schema identities and their dates against the recorded ones. | A specific classified drift — a schema promoted, deprecated or retired. |
| Prose (`rest-api.md`, `fix-api.md`, `demo-mode/general-info.md`, and the rest) | **Digest-level.** Record the SHA-256 of the raw document; compare digests. | `REVIEW_REQUIRED`. A human re-reads the document. |

The refresh never re-derives a capability row from prose. It detects **that a
document changed**, and a person decides what that means. This is less capable
than automatic extraction and more honest than it: an extractor that silently
mis-parses a changed table produces a confident wrong registry, which is the
failure mode ADR-0086 names as characteristic.

Where a source is machine-readable, the stricter regime applies, and the registry
records which regime each source is under. A source cannot be quietly demoted to
digest-level to avoid a failing comparison.

### 5. The refresh is a quality gate, and the application still connects to nothing

`python -m tools.quality.venue refresh` reaches the network.
`globin api-reality …` does not, and neither does anything else under `src/globin`.

Three reasons, and the first decides it:

1. The property that no module in the package opens an outbound connection is
   currently **proved**, not asserted. Spending it to fetch Markdown would be a
   poor trade; Phase 045 delivers the REST transport and is where the package
   earns an outbound client, with the rule widened deliberately and in its own
   diff.
2. The refresh maintains a **committed repository file**. GLOBIN's wheel holds the
   package and its metadata and nothing else, so an installed GLOBIN has no
   `docs/` to refresh and no `tools/` to invoke. The capability would be present
   and unusable.
3. `tools/quality/wheels` already does exactly this: an offline verb as the
   default, a networked verb as the opt-in, an injected fetcher so the network
   path is exercised without a network, and `https` checked rather than trusted.

The fetcher is injected, and that is not a convenience. The offline guarantee is
enforced by refusing sockets in the *test* process; a real fetch inside a test
would be caught by the guard in the wrong direction, proving only that the guard
works.

The refresh reads **official machine-readable resources and never rendered
pages**. [ADR-0004](0004-official-apis-only-no-scraping.md) and `SOURCE_POLICY.md`
require it, the latter naming documentation ingestion specifically. Raw documents
from the official specification repository, and the lifecycle JSON beside them.

A refresh that fails leaves the committed registry byte-identical. A regenerated
registry that fails its own validation is written beside the committed one and the
committed one is untouched, which is the pattern `lock relock` already uses.

### 6. Three environment kinds, and internal simulation is deliberately absent

`EnvironmentKind` is `PRODUCTION`, `DEMO`, `TESTNET`.

[ADR-0006](0006-product-and-environment-capability-matrix.md) names four classes,
the fourth being internal simulation. It is absent here because this registry
records what Binance documents, and Binance documents no simulator of GLOBIN's.
Admitting a fourth member would put a row in the registry that no official source
could ever establish, in the one artefact whose whole purpose is that every row has
one. Row 035 owns it, and ADR-0006's rule that the four are never conflated is
served by the registry being unable to express the fourth rather than by convention.

### 7. A query distinguishes an absent entry from a recorded `UNKNOWN`

ADR-0006's third rule — an unmapped product and environment combination is refused,
never downgraded and never falling back to production — is called there *"the
single most important safety property in this ADR."*

The query surface therefore never collapses those two answers. *There is no entry
for this combination* and *there is an entry and it records `UNKNOWN`* are
different returns, because the first means the registry has not been told and the
second means the documents do not say. Both refuse; they refuse for different
reasons and a caller that cannot tell them apart cannot report which.

Nothing refuses an *operation* yet, because there are no operations. What this
phase delivers is a surface on which the refusal is expressible; Phase 036 makes it
binding and Phase 037 gives it a caller.

## Consequences

**A new Binance fact is a change to one file.** The registry is the only place a
base URL, a port, a key-type restriction or a schema version is written. An
architecture test fails if a Binance endpoint literal appears anywhere else under
`src/globin`.

**The registry can be wrong and pass every gate.** Every check here is internal
consistency and provenance presence; nothing verifies that a recorded fact matches
the document it cites, because doing so is the prose extraction this record
refuses. What the gate guarantees is that a wrong row is *attributable* — it names
the document and the date it was read.

**The refresh is outside `full`, so it can be not-run indefinitely.** That is the
accepted cost of `full` working on an aeroplane. The residual risk and its
observable signal are in ADR-0086.

**Six status words means six cases downstream.** Every consumer from Phase 036
onward has to handle `RESTRICTED` and `ANNOUNCED` rather than treating anything
that is not `SUPPORTED` as absent. That is more work than a boolean and it is the
work the phase exists to force.

**No new exit code, and no new bootstrap check.** 26 remains free. Nothing in a
GLOBIN start-up consumes the registry, so a `CheckSpec` row would be a check with
no consumer. The code that names a refused unmapped combination belongs to the
phase that has a caller able to produce it.

## Alternatives Considered

**Parse the prose documents and derive capability rows automatically.** Rejected:
the trade is determinism for coverage, and it loses. An extractor is correct until
a table gains a column, and its failure mode is a plausible registry rather than an
error. The digest regime detects the same change and returns a question instead of
an answer.

**One status enumeration shared with `CapabilityStatus`.** Rejected: five of the
eight resulting members would be unreachable from one of the two callers, and a
change made for a host capability would silently alter the vocabulary describing a
venue. The shared spellings are a coincidence of English.

**A boolean `supported` with a separate `notes` field.** Rejected for the reason
the phase exists: it cannot distinguish *not documented* from *documented absent*,
and every consumer would re-derive the distinction from prose notes, badly.

**Put the refresh in `globin.adapters` and widen the socket rule now.** Rejected as
premature: the widening is Phase 045's, where an outbound client has a caller and
the rule can be reshaped once rather than twice. Deferring costs nothing here
because the refresh has no runtime consumer.

**Vendor the SBE schema XML files into the repository.** Rejected: `SOURCE_POLICY.md`
states that copies go stale invisibly and that knowing the source beats holding a
snapshot of it. The lifecycle metadata and a digest give the same verification
without a second copy of a specification this repository does not parse.

**Model `EnvironmentKind` with a fourth `INTERNAL_SIMULATION` member for
completeness.** Rejected: it would be a member no official source could populate,
in the artefact whose invariant is that every row has one.

## Risks and Trade-offs

**The characteristic failure mode is a digest that changes for an editorial
reason.** A typo fix in `rest-api.md` produces `REVIEW_REQUIRED` drift with nothing
behind it, and a reviewer who sees several of those in a row learns to wave them
through — which is exactly when the substantive one arrives. The observable signal
is a drift review closed with no registry change more than a few times running. No
mitigation is claimed; section-level digests were considered and rejected as
re-introducing prose parsing to decide where a section ends.

**A second risk is that `RESTRICTED` becomes a place to put anything awkward.** It
means documented-subject-to-a-condition, and a record using it must name the
condition. If it starts appearing with vague conditions it has become a synonym for
`UNKNOWN`, and the signal is a rising count of `RESTRICTED` rows whose condition
text is generic.

**A third is that the two-regime split hides how little is verified.** The
structured regime covers the SBE and FIX schema lifecycle, which is four documents.
Everything else — every endpoint, every auth rule, every environment semantic — is
under the digest regime, which verifies that a document is unchanged and nothing
about whether it was read correctly in the first place. That proportion is stated
in `BINANCE_API_REALITY.md` rather than left to be discovered.

**A fourth is the one this phase cannot mitigate.** The registry's correctness on
the day it was written rests on a person reading documents. `SOURCE_POLICY.md`
requires re-verification when a phase depends on a fact, and Phases 037 onward must
re-read what they use rather than trusting a row because it is typed.

## References

- [`../engineering/BINANCE_API_REALITY.md`](../engineering/BINANCE_API_REALITY.md) — how to read, refresh and verify the registry.
- [`../research/phase_033_sources.md`](../research/phase_033_sources.md) — the sources every row rests on.
- [`../SOURCE_POLICY.md`](../SOURCE_POLICY.md) — the authority tiers and the prohibition on scraping rendered pages.
- [`../SERIALIZATION_POLICY.md`](../SERIALIZATION_POLICY.md) — the canonical rendering the snapshot and digest use.
- [ADR-0004](0004-official-apis-only-no-scraping.md) — official machine-readable sources only.
- [ADR-0006](0006-product-and-environment-capability-matrix.md) — the four environment classes and the refusal rule.
- [ADR-0086](0086-phase-033-widens-to-deliver-the-binance-api-reality-registry.md) — the amendment this record's decisions belong to.

## Supersedes

Nothing.

## Superseded By

Nothing.
