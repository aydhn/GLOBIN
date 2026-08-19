# Documentation Ingestion and Change Tracking

How GLOBIN consumes Binance's official documentation, how often it must go back,
and what happens when a document it depends on has moved.

The decision behind it is
[ADR-0088](../adr/0088-phase-034-widens-to-deliver-the-rest-transport-substrate.md).

---

## What Phase 033 already built

This document completes a subject rather than starting one. Phase 033 delivered:

- an allowlisted refresh over official machine-readable sources;
- a SHA-256 digest per source, recorded in
  [`binance-api-reality.toml`](binance-api-reality.toml);
- a deterministic, classified diff between two snapshots.

[`scope-amendments.toml`](scope-amendments.toml) recorded what was deliberately
absent: *"no cadence, no accumulated change log across runs, no review workflow for
a breaking drift."* Those three are what this adds.

---

## Cadence

[`ingestion-policy.toml`](ingestion-policy.toml) declares a re-check interval per
**regime**, not per source. A source's regime already says how it can be
re-checked, and that is what determines how cheap and how reliable a re-check is.
Sixteen per-source rows would be sixteen numbers nobody could justify individually,
and the first one anybody edited would be the one nobody noticed.

| Regime | Interval | Why |
|---|---|---|
| `structured` | 14 days | Machine-readable, compared field by field, one HTTP request |
| `digest` | 30 days | A digest is exact; what a change *means* needs a person |
| `manual` | 90 days | No fetchable text form; the only re-check is somebody reading it |
| *(anything else)* | 7 days | A regime nobody wrote a rule for is one nobody reasoned about |

The default is the **tightest** interval, not the loosest. That is the direction
that fails safe.

Every rule carries a `reason`. A cadence is GLOBIN's own judgement rather than a
venue fact, so it argues for itself where a registry row cites a document.

### The boundary is strictly greater than

A source read exactly `recheck_days` ago is still fresh; it goes stale the
following day. The alternative makes `recheck_days = 1` mean *stale after zero
days*, which is not what anybody writing that intends. Both implementations use the
same rule and `tests/contract/test_ingestion_contract.py` compares them across four
dates and every regime — an off-by-one between them would mean the gate reporting a
source as fresh while the transport refused to use it.

### Three states, not two

| State | Means |
|---|---|
| `fresh` | Read within its cadence. May be relied on |
| `stale` | Past its cadence. **Everything resting on it fails closed** |
| `ahead_of_clock` | Recorded as read *later* than the date being compared against |

The third is not an error. A machine whose clock is behind the registry produces a
negative age, which says something true about the *machine* rather than about the
source. It is never treated as stale — a record cannot be too old to trust because
this computer is wrong — and never silently called fresh either, because an
operator whose clock is days out wants to know that before they debug anything
else.

---

## What ageing does, and what it deliberately does not

**A stale source refuses a REST resolution.**
`globin.domain.rest_endpoint.resolve` returns `SOURCE_STALE` before any socket
opens. A record nobody has re-read may be describing a venue that has moved, and
acting on it is the optimistic acceptance
[`REST_TRANSPORT.md`](REST_TRANSPORT.md) exists to prevent.

**A stale source does not fail `python -m tools.quality venue`.** It is reported as
a *note* rather than a finding. A gate that reddened on a calendar — on a machine
that may have no network to clear it with — is a gate people learn to re-run rather
than read. The transport fails closed; the repository gate reports.

---

## Two readers, one document

`src/globin/adapters/ingestion.py` and `tools/quality/venue/ingestion.py` parse the
same file and share no code. That is the arrangement Phase 033 built for the
registry, and it is only worth anything because
`tests/contract/test_ingestion_contract.py` compares what the two see.

They read different halves on purpose:

| | `[default]` + `[cadence]` | `[review]` |
|---|---|---|
| The package | ✓ — staleness is what the transport fails closed on | ✗ |
| The gate | ✓ | ✓ — acknowledging a change is a repository act |

---

## The change journal

`refresh` appends one JSON object per run **that found something** to
`.globin/venue/venue-journal.jsonl`: the registry digest, how many sources were
checked, and every finding.

Append-only, and a run that found nothing appends nothing. Two runs over an
unchanged venue therefore leave the journal byte-identical, which is what makes it
readable — every line in it is a moment something moved.

```bash
python -m tools.quality.venue journal
```

The journal is machine-local. `.globin/` is not committed: it is a record of what
*this machine* observed, not a claim about the repository.

---

## Breaking-drift review

`refresh` compares each source's fetched SHA-256 against the digest the registry
records. A document whose digest moved produces `API_REALITY_SOURCE_CHANGED`, and
the gate **fails** until one of two things happens:

1. somebody re-reads the document and updates the registry — the right answer
   almost every time; or
2. somebody records in
   [`venue-acknowledgements.toml`](venue-acknowledgements.toml) that they looked
   and the change did not affect GLOBIN's record.

### Why a person and not an extractor

[`BINANCE_API_REALITY.md`](BINANCE_API_REALITY.md) states the rule: the registry
never re-derives a capability from prose, because an extractor that mis-parses a
changed table produces a *confident wrong registry*, which is worse than a prompt
to re-read. This ledger is where that prompt is answered.

### The ledger fails in both directions

| | Fails |
|---|---|
| A source-changed finding with no row | `API_REALITY_DRIFT_UNACKNOWLEDGED` |
| A row whose finding no longer occurs | `API_REALITY_ACKNOWLEDGEMENT_STALE` |

The second is what keeps it honest. An acknowledgement that outlived its finding is
a standing permission nobody re-examined — the same bargain
[`wheel-survey.toml`](wheel-survey.toml) strikes for an owned gap: fine until the
gap closes, and then the record must go.

### The key is required and may be empty

`acknowledged_reasons` must be present. An empty list is a policy saying no finding
needs a written decision — legitimate, and visible. A *missing* key is a typo, and
defaulting it to empty would turn one into permission.

Reasons are named by the gate's own finding constants rather than by a severity
word. A severity would be a second vocabulary to keep in step with the one the gate
already emits, and the first time the two disagreed the rule would fire on the
wrong thing.

---

## The state today

Every source digest was verified during Phase 034 and every one still matched what
Phase 033 recorded — `rest-api.md` hashes to `sha256:49ea6809…`, character for
character what the registry carries. There has been no drift to acknowledge, so the
ledger is **empty**, and an empty ledger is not permissive: with no rows, *any*
source-changed finding fails the gate.

Sixteen sources are declared. One — the developer-documentation catalogue — cannot
be re-checked at all, and no REST endpoint rests on it, so its cadence gates nothing
today. It is declared so that the day one does, the ageing is already in place.

---

## Commands

```bash
python -m tools.quality.venue check
```

Recompute the registry and age every source. Reaches nothing. The default.

```bash
python -m tools.quality.venue refresh
```

Everything `check` does, then ask the venue whether the record is still true.
Reaches the network, appends the journal, and enforces the acknowledgement ledger.

```bash
python -m tools.quality.venue journal
```

Read back what previous refreshes recorded. Reaches nothing, writes nothing.

Freshness also reaches the running application:

```bash
.venv\Scripts\globin.exe rest endpoints --json
```

carries the whole freshness report beside the resolution survey, and
`globin rest evidence` records it in the Phase 034 manifest.
