# Binance API Reality Registry

What Binance is recorded as documenting, how sure GLOBIN is of each claim, and how
to tell when that stops being true.

Delivered by Phase 033 under [ADR-0086](../adr/0086-phase-033-widens-to-deliver-the-binance-api-reality-registry.md),
with the technical decisions in [ADR-0087](../adr/0087-the-api-reality-registry-is-declared-with-provenance-and-drift-is-measured-in-two-regimes.md).

> **This is a dated snapshot of documentation, not runtime truth about the venue.**
> Every row records what a named document said on a named day. Nothing here has ever
> been confirmed against a live response, because GLOBIN has never contacted Binance.

---

## Why it exists

Everything from Phase 034 onward is built on assumptions about what Binance
exposes. Carried in prose, in memory, or as string literals scattered through
adapters, those assumptions are inherited silently and are wrong invisibly.

The registry gives them one home, a source each, and a way to notice when a source
changes.

[ADR-0006](../adr/0006-product-and-environment-capability-matrix.md) states the
rule this serves, in Phase 001's words: *"If the matrix has no entry for a requested
product and environment combination, the operation is **refused**. It is never
silently downgraded, and never falls back to production."* That refusal needs
something to consult, and this is it.

---

## Product, environment and protocol are three dimensions

They are independent, and flattening any two of them loses something real.

- A **product family** is what Binance sells: Spot, Cross Margin, USDⓈ-M Futures.
  Which families exist is Binance's to decide and changes without GLOBIN being
  redeployed, so families are **data in the registry**, never an enumeration in
  code. `tests/architecture/test_identifier_discipline.py` enforces that, and it
  refused the first draft of this phase for exactly that reason.
- An **environment** is which copy of the venue you are talking to. Coverage
  differs *per product*: Spot has three, and what the other families have is not
  something an admissible source could tell us.
- A **protocol** is how you talk to it: REST, WebSocket API, WebSocket market
  streams, WebSocket user streams, and three separate FIX session types.

A capability belongs to the **triple**, never to the product. Spot REST accepts
HMAC, RSA and Ed25519; Spot FIX accepts **Ed25519 only**. Copying one product's
auth reality onto another is the mistake the model is shaped to prevent.

---

## Production, demo and testnet

Three environments, and Binance itself tabulates the difference between the two
non-production ones.

| | Testnet | Demo Mode |
|---|---|---|
| Hosts | `testnet.binance.vision` | `demo-*.binance.com` |
| Order books | *independent* of the live exchange | *similar to* the live exchange |
| Balances | reset monthly | reset on request |
| Limits and filters | *generally* the same as live | *exactly* the same as live |
| Features | may appear here first | always the same as live |
| Endpoint coverage | `/api` only — `/sapi` is refused | as live |

Binance adds a warning worth repeating: realistic market data is not real market
data, and a strategy that works in Demo Mode is not thereby shown to work live.

A single `is_testnet` boolean would erase all of that. So would treating
"not production" as one thing.

**Every non-production environment declares a `host_marker`** — the substring its
hosts are spelled with. That is what lets the registry refuse an endpoint filed
under `testnet` whose host is `api.binance.com`, which is the failure ADR-0006
calls the dangerous one.

---

## Why `unknown` is not `unsupported`

The six status words are the point of the phase.

| Word | Means |
|---|---|
| `supported` | Documented, no condition attached. |
| `restricted` | Documented, subject to a **stated** condition. A row using this must name it. |
| `deprecated` | Documented, still reachable, announced as going away. |
| `announced` | Documented as scheduled, not yet available. |
| `unsupported` | Documented as **not** available. A stated absence. |
| `unknown` | The documents do not say, or no admissible source could be read. |

**`unknown` is never a synonym for no.** Most non-Spot rows in this registry carry
it, and the reason is structural rather than lazy: see the next section.

`unsupported` currently appears **zero** times. That is deliberate — it is a claim
that a document states an absence, and none of the documents read for this phase
states one.

Each row also carries an **evidence kind**: `documented`, `inferred` or `observed`.
**Nothing may be `observed`**, and a contract test fails if a row claims it. GLOBIN
has never contacted the venue; the member exists because Phase 045 will have a
transport.

---

## What the registry knows, and what it does not

Binance publishes an official machine-readable specification for **Spot** and for
no other product family. The derivatives, options, portfolio margin and margin
documentation is a client-rendered application with no fetchable text form — the
former GitHub Pages site now redirects to it.

[`SOURCE_POLICY.md`](../SOURCE_POLICY.md) forbids scraping rendered pages, and
forbids *"any generated summary of an API, including from a language model, used in
place of reading the specification."* Both routes to a derivatives fact are
therefore closed, and the honest record is `unknown`.

That prohibition earned itself during Phase 033: a summarizer asked for the COIN-M
testnet WebSocket host returned the **Spot** demo host, with no indication of doubt
([`../research/phase_033_sources.md`](../research/phase_033_sources.md), S-11).

Roughly, as recorded on 2026-08-19:

| | Count |
|---|---|
| Product families | 13 |
| Product-and-protocol surfaces | 42 |
| Product-and-environment pairs | 24 |
| Endpoints | 58, all Spot |
| Schema versions | 11 |
| Sources | 15, of which 1 cannot be re-checked at all |

Ask the registry itself rather than trusting this table:

```bash
.venv\Scripts\globin.exe api-reality show
```

---

## Reading it

Seven read-only verbs. None writes, none refreshes, none reaches a network.

```bash
.venv\Scripts\globin.exe api-reality products
```

```bash
.venv\Scripts\globin.exe api-reality environments
```

```bash
.venv\Scripts\globin.exe api-reality capability unknown
```

`show`, `products`, `surfaces`, `environments`, `capability [STATUS]`, `verify` and
`diff PATH`. Under `--json`, standard output carries JSON and nothing else.

**A query distinguishes an absent entry from a recorded `unknown`.** `None` means
the registry was never told; a record carrying `unknown` means the documents do not
say. Both refuse, for different reasons, and a caller that cannot tell them apart
cannot report which.

---

## Verifying it

```bash
python -m tools.quality venue
```

Recomputes every claim from the document and writes
`.globin/venue/api-reality-manifest.json`. It reaches nothing.

**The gate is a second reader.** Nothing under `tools/` imports `globin`, so
`globin.adapters.api_reality` and `tools/quality/venue/plan.py` parse the same
document with no shared code — a registry the package would mis-read is caught by a
reader that shares none of its assumptions. A contract test compares what the two
see.

What fails: a repeated identity, a cited source that is not declared, a source
location off the allowlist, a row claiming `observed`, a `restricted` row naming no
condition, two current schemas for one family, an endpoint scheme that is not
encrypted, a FIX endpoint that does not require TLS **and** SNI, and an endpoint
whose host contradicts its environment.

---

## Refreshing it

```bash
python -m tools.quality.venue refresh
```

Everything `check` does, and then asks the official sources whether the record still
holds. **It reaches the network**, which is why it is a separate word and why
neither verb is in `full` — `full` runs before every commit and must work on an
aeroplane.

Safety, all of it structural rather than intended:

- **`https` only**, and the host is checked against an allowlist by parsed
  hostname. `raw.githubusercontent.com` and `github.com` are additionally
  restricted to Binance's own organisation.
- **Redirects are refused, not followed.** Following one is how an allowlist stops
  meaning anything.
- **Bounded** response size, timeout, and an explicit user agent.
- **The fetcher is injected**, so every network branch is exercised in tests
  without a network. The default is the real one.
- **Nothing is written to the registry.** A refresh reports; it does not edit. The
  committed document is byte-identical whatever the answer.

The refresh lives outside the package deliberately. No module in `src/globin` opens
an outbound connection — a property `tests/architecture/test_library_discipline.py`
proves rather than asserts — and Phase 045 is where the application earns an
outbound client.

---

## Two drift regimes, and a third that is not one

| Regime | Sources | How a change is detected |
|---|---|---|
| `structured` | The 4 SBE schema lifecycle files | Parsed. Compared field by field. |
| `digest` | The 10 raw Markdown documents | SHA-256 compared. A change is `review_required`. |
| `manual` | The developer-docs catalogue | **Cannot be re-checked at all.** |

The registry never re-derives a capability row from prose. It detects *that a
document changed*, and a person decides what that means. An extractor that
mis-parses a changed table produces a confident wrong registry, which is worse than
a prompt to re-read.

> **Three of Binance's four lifecycle files are not valid JSON today.**
> `sbe_fix_schema_lifecycle_prod.json` and its testnet twin close an array with a
> trailing comma; `sbe_schema_lifecycle_testnet.json` omits a comma between two
> entries. Measured, not remembered — see S-10.
>
> Each is marked `known_unparseable` in the registry. An **owned** defect is
> recorded; an unowned one fails. And a source declared unparseable that starts
> parsing **also fails**, so the exemption cannot outlive its reason.

This means the structured regime covers, in practice, **one** file. That proportion
is stated here rather than left to be discovered.

---

## Reviewing drift

```bash
.venv\Scripts\globin.exe api-reality diff PATH
```

A pure function over two snapshots — no network, no clock. Exits `1` when any
finding is more than informational, so it is usable in a pipeline without anybody
reading the output.

Four risk levels, and the split between the last two is the useful one:

- `informational` — something appeared. Nothing GLOBIN relied on changed.
- `review_required` — a person must look. Every prose-digest change lands here.
- `breaking` — something GLOBIN could rely on stopped being available.
- `security_relevant` — an authentication or key rule changed. A broken surface is
  re-planned; a changed key rule is checked against what GLOBIN holds **first**.

Two classifications worth knowing:

- **`supported` → `unknown` is breaking**, not informational. A capability GLOBIN
  could describe is now one it cannot, and treating a loss of knowledge as news is
  how a registry decays quietly.
- **A schema retirement is breaking; a deprecation is not.** Binance documents at
  least six months of support after deprecation, so one is a deadline and the other
  is a closed door.

---

## Source authority

[`SOURCE_POLICY.md`](../SOURCE_POLICY.md) governs. In brief, for this registry:

- The official `binance-spot-api-docs` repository and the Binance Developer
  Documentation are the only things that can establish a fact.
- A source location must be on the allowlist, and a GitHub path must name Binance's
  own organisation. A fork is not a specification.
- **A source consulted in an earlier phase is evidence about that date.** Phases 037
  onward must re-read what they use rather than trusting a row because it is typed.
- A source earns its place by supporting a claim **or** by being re-checkable. The
  changelog supports no row and is watched, because it is where a change is
  announced before anything else moves.

---

## What this phase did not do

- **No transport.** No REST client, no WebSocket client, no FIX session. Nothing
  connects.
- **No signing.** No HMAC, RSA or Ed25519 operation. No credential is read,
  required or held.
- **No per-operation endpoints.** Base URLs and endpoint families only — paths,
  methods, security types and weights are Phase 037 and Phase 041.
- **No refusal at runtime.** The query surface can *express* an unmapped
  combination; nothing consults it yet, because there are no operations. Phase 036.
- **No internal simulation.** ADR-0006 names four environment classes and Binance
  documents three. The fourth is Phase 035's, and the registry deliberately cannot
  express it — a member no official source could populate has no place in the one
  artefact whose invariant is that every row has one.
- **No cadence.** The refresh exists; deciding how often to run it, and what to do
  with an accumulated change log, is Phase 034.

---

## How Phase 034 onward should consume this

1. **Never spell a Binance host.** `tests/architecture/test_api_reality_discipline.py`
   fails if any string constant in `src/globin` contains one. Resolve an endpoint
   through the registry.
2. **Handle all six status words.** Treating anything that is not `supported` as
   absent throws away `restricted`, `deprecated` and — most importantly — the
   difference between `unknown` and `unsupported`.
3. **Read the condition on a `restricted` row.** It is there because using the
   surface depends on it.
4. **Re-verify before depending.** A row is evidence about the date in its source,
   and `SOURCE_POLICY.md` requires the phase that depends on a fact to check it.
5. **Add a source before adding a claim.** A row citing an undeclared source is
   refused by both readers.
