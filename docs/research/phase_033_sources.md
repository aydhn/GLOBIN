# Phase 033 — Source Ledger

Sources consulted while building the Binance API reality registry, recorded under
[`../SOURCE_POLICY.md`](../SOURCE_POLICY.md). This is the first phase in the
programme whose subject is a venue rather than this repository or this host, so it
is the first whose ledger carries facts that can go stale without anything here
changing.

**Two entries changed a decision, and both are measurements rather than readings.**
S-05 found that a FIX session's request encoding and response encoding are selected
independently by port, which broke a one-encoding-per-endpoint model before it was
written. S-10 found that three of the four machine-readable lifecycle files Binance
publishes are not valid JSON, which decided how the refresh must behave when a
structured source will not parse.

**Every fact below was read from raw bytes.** The documents were fetched with
`curl` and searched directly; nothing here rests on a rendered page or on a
generated summary of one. `SOURCE_POLICY.md` prohibits the latter in as many words,
and S-11 records a measured instance of why.

Where an admissible source could not be reached, the registry records `UNKNOWN`
rather than a best guess. That is not a gap in the research; it is the phase's
central claim made operational — *not documented* and *documented absent* are
different facts.

---

### S-01 — Binance publishes an official machine-readable specification for Spot, and for no other product family

- **Canonical location:** Binance, *Official Documentation for the Binance Spot APIs
  and Streams* —
  `https://github.com/binance/binance-spot-api-docs`
- **Accessed:** 2026-08-19
- **Authority:** Primary. `SOURCE_POLICY.md` names this repository by name as
  authoritative for Binance API behaviour.
- **Supports:** The repository root holds `rest-api.md`, `web-socket-api.md`,
  `web-socket-streams.md`, `user-data-stream.md`, `fix-api.md`,
  `sbe-market-data-streams.md`, `enums.md`, `errors.md`, `filters.md`,
  `CHANGELOG.md`, and the directories `demo-mode/`, `testnet/`, `fix/schemas/` and
  `sbe/schemas/`. Every one is fetchable as raw text. No equivalent repository
  exists for Margin, USDⓈ-M Futures, COIN-M Futures, Options or Portfolio Margin.
- **Implication for GLOBIN:** The registry's source coverage is asymmetric, and the
  asymmetry is a property of Binance rather than of this phase. Spot facts are
  readable, digest-monitorable and refreshable. Facts about every other product
  family are not reachable by any means `SOURCE_POLICY.md` admits, so they are
  recorded `UNKNOWN` with that as the stated reason. Phase 034 owns finding an
  admissible route; Phase 037 owns the endpoints that route would establish.

### S-02 — Spot REST has six production base endpoints, and a seventh that serves market data only

- **Canonical location:** Binance, *General API Information*, `rest-api.md` lines
  84-100 —
  `https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/rest-api.md`
- **Accessed:** 2026-08-19
- **Authority:** Primary.
- **Supports:** `https://api.binance.com`, `https://api-gcp.binance.com`,
  `https://api1.binance.com`, `https://api2.binance.com`, `https://api3.binance.com`
  and `https://api4.binance.com`, with the note that the last four *"should give
  better performance but have less stability"*. Separately: *"For APIs that only
  send public market data, please use the base endpoint
  **https://data-api.binance.vision**."*
- **Implication for GLOBIN:** A base URL is not one string per product and
  environment. The registry models an endpoint family as carrying several hosts,
  and records the market-data-only host as a distinct entry with no trading and no
  user-stream capability, so that a later phase cannot route a signed request to it
  by picking the first URL in a list.

### S-03 — Spot accepts three key types, and there are exactly four endpoint security types

- **Canonical location:** Binance, *General API Information* and *Endpoint security
  type*, `rest-api.md` lines 98 and 199-213 —
  `https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/rest-api.md`
- **Accessed:** 2026-08-19
- **Authority:** Primary.
- **Supports:** *"We support HMAC, RSA, and Ed25519 keys."* The security types are
  `NONE` (public market data), `TRADE`, `USER_DATA` and `USER_STREAM`. The document
  also states that HMAC signatures are *"not case-sensitive"* while RSA and Ed25519
  signatures are case-sensitive.
- **Implication for GLOBIN:** `AuthMechanism` and `ApiKeyType` are separate axes in
  the registry: what a request must carry, and what algorithm may sign it. The
  case-sensitivity difference is recorded but not acted on — Phase 038 implements
  signing, and a registry that encoded signature encoding rules would be building it.

### S-04 — FIX sessions accept Ed25519 keys only, and each session type demands a named key permission

- **Canonical location:** Binance, *FIX API*, `fix-api.md` lines 114-161 —
  `https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/fix-api.md`
- **Accessed:** 2026-08-19
- **Authority:** Primary.
- **Supports:** *"**FIX sessions only support Ed25519 keys.**"* Order Entry:
  *"Only API keys with `FIX_API` are allowed to connect."* Drop Copy and Market
  Data: *"Only API keys with `FIX_API` or `FIX_API_READ_ONLY` are allowed to
  connect."*
- **Implication for GLOBIN:** A capability recorded against one product must never
  be inherited by another, and this is the sharpest available example: Spot FIX
  refuses HMAC and RSA, which Spot REST accepts. The registry therefore attaches
  `ApiKeyType` to the product-environment-protocol triple rather than to the
  product. `KeyPermission` is modelled as its own vocabulary because `FIX_API` and
  `FIX_API_READ_ONLY` are not symbol permissions and do not appear in `enums.md`.

### S-05 — A FIX session's request encoding and its response encoding are selected independently, by port

- **Canonical location:** Binance, *FIX API — Endpoints* (SBE section), `fix-api.md`
  lines 1402-1424 —
  `https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/fix-api.md`
- **Accessed:** 2026-08-19
- **Authority:** Primary.
- **Supports:** *"In addition to FIX encoding available on port 9000, two
  request/response encoding schemes are supported on additional TCP ports."* Then,
  per session type: port `9001` — *"Send FIX requests; receive FIX SBE responses"*;
  port `9002` — *"Send FIX SBE requests; receive FIX SBE responses"*. Port `9001`
  additionally requires the `SbeSchemaId` (tag 25050) and `SbeSchemaVersion`
  (tag 25051) tags to be set.
- **Implication for GLOBIN:** **This changed a decision.** The registry was designed
  with one `EncodingKind` per surface, which cannot express port 9001 at all — it is
  neither FIX-text nor FIX-SBE but both, in opposite directions. An endpoint record
  now carries `request_encoding` and `response_encoding` separately, and the
  identity of a FIX endpoint includes its port. Nine FIX endpoints per environment
  follow from three session types times three ports, and a model with three would
  have silently lost six.

### S-06 — FIX requires SNI and hostname validation, and Drop Copy is delayed by one second

- **Canonical location:** Binance, *FIX API*, `fix-api.md` lines 87-133 —
  `https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/fix-api.md`
- **Accessed:** 2026-08-19
- **Authority:** Primary.
- **Supports:** *"please make sure that your client sends **SNI (Server Name
  Indication)** during the TLS handshake and performs certificate validation against
  the intended hostname. Clients that do not send SNI may receive an unexpected
  certificate, which can result in TLS handshake or hostname verification
  failures."* And, of Drop Copy: *"Data in Drop Copy sessions is delayed by 1
  second."*
- **Implication for GLOBIN:** TLS and SNI are recorded as declared requirements on
  the FIX endpoint records rather than left to whichever library Phase 047 chooses,
  because the failure mode of omitting SNI is receiving *a certificate* rather than
  no certificate. The Drop Copy delay is recorded as a documented semantic so that a
  later reconciliation phase cannot treat Drop Copy as a real-time mirror of Order
  Entry.

### S-07 — Demo Mode and Testnet are different environments, and Binance tabulates the difference

- **Canonical location:** Binance, *Demo Mode for SPOT Trading*,
  `demo-mode/general-info.md` lines 35-253 —
  `https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/demo-mode/general-info.md`
- **Accessed:** 2026-08-19
- **Authority:** Primary.
- **Supports:** Demo Mode has its own hosts: `https://demo-api.binance.com/api`,
  `wss://demo-ws-api.binance.com/ws-api/v3`, `wss://demo-stream.binance.com`,
  `wss://demo-stream-sbe.binance.com`, and `demo-fix-oe`, `demo-fix-dc`,
  `demo-fix-md` on ports 9000, 9001 and 9002. The comparison table states:
  *"Balances are reset every month"* against *"You can reset your balance whenever
  you want via the UI"*; *"Testnet's prices and order books are independent from the
  live exchange"* against *"Demo Mode's prices and order books are similar to the
  live exchange"*; and *"generally the same as the live exchange"* against
  *"exactly the same as the live exchange"* for IP limits, unfilled order count and
  exchange filters. A warning follows: *"Realistic market data is not equal to 'real'
  market data."*
- **Implication for GLOBIN:** ADR-0006's rule that the environment classes are never
  conflated is now backed by recorded semantics rather than by assertion, and
  `EnvironmentKind` cannot be a boolean. It also **records a drift against this
  repository's own accepted record**: ADR-0006 states that Demo Mode *"runs on
  production infrastructure"*, sourced from Phase 001. Demo Mode is served from
  `demo-`-prefixed hosts distinct from the production ones. Whether the
  infrastructure behind them is shared is not something the documentation says, so
  the registry records the hosts, records the semantics Binance does state, and
  records the claim as unverified. ADR-0006 is immutable and is not edited.

### S-08 — Spot Testnet serves `/api` only, and `/sapi` is refused there

- **Canonical location:** Binance, *SPOT Testnet*, `testnet/general-info.md` lines
  12-31 —
  `https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/testnet/general-info.md`
- **Accessed:** 2026-08-19
- **Authority:** Primary.
- **Supports:** The endpoint table pairs each production host with its testnet
  counterpart: `https://testnet.binance.vision/api` and
  `https://api1.testnet.binance.vision/api`,
  `wss://ws-api.testnet.binance.vision/ws-api/v3`,
  `wss://stream.testnet.binance.vision`,
  `wss://stream-sbe.testnet.binance.vision`, and `fix-oe`, `fix-dc`, `fix-md` at
  `testnet.binance.vision` on all three ports. Under *"Can I use the `/sapi`
  endpoints on the Spot Test Network?"*: *"No, only the `/api` endpoints are
  available on the Spot Test Network"*. The same table is the only admissible source
  found for the production SBE stream hosts `wss://stream-sbe.binance.com/ws` and
  `wss://stream-sbe.binance.com/stream`.
- **Implication for GLOBIN:** Coverage differs per environment within a single
  product, not merely per product. The registry records endpoint families per
  product *and* environment, so that `/sapi` on testnet is an absent entry rather
  than an inherited one — which is what ADR-0006's refusal rule needs in order to
  refuse anything.

### S-09 — The SBE schema lifecycle is published as machine-readable JSON, and the changelog treats it as the record

- **Canonical location:** Binance, *SBE schema lifecycle (Production)* and
  *CHANGELOG*, entries dated 2026-06-22 and 2026-07-01 —
  `https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/sbe/schemas/sbe_schema_lifecycle_prod.json`
- **Accessed:** 2026-08-19
- **Authority:** Primary.
- **Supports:** The file records `latestSchema` id 3 version 5, released
  `2026-07-07`; four deprecated schemas; and six retired ones, each with
  `releaseDate`, `deprecatedDate` and where applicable `retiredDate`. The changelog
  entry of 2026-06-22 reads *"The SBE lifecycle for Production has been updated to
  reflect this change."* The SBE FAQ states *"A deprecated schema will be supported
  for at least 6 months after deprecation."* The FIX SBE lifecycle is a separate
  file recording id 1 version 1 as latest, released `2026-03-25`.
- **Implication for GLOBIN:** This is the only Binance source that is structured
  rather than prose, and it is what makes field-level drift detection possible at
  all. The registry compares schema identities and dates directly against it. Every
  other source is compared by digest, because deriving a capability from prose
  automatically would produce a confident guess. SBE and FIX SBE lifecycles are
  tracked as separate schema families, because their identifiers collide — both
  number from 1 — and merging them would make `1:1` ambiguous.

### S-10 — Three of the four lifecycle files Binance publishes are not valid JSON

- **Canonical location:** Binance, `sbe/schemas/` —
  `https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/sbe/schemas/sbe_fix_schema_lifecycle_prod.json`
- **Accessed:** 2026-08-19
- **Authority:** Primary, and **measured rather than read**: each file was fetched
  and passed to Python's `json.load`.
- **Supports:** `sbe_schema_lifecycle_prod.json` (1306 bytes) parses.
  `sbe_fix_schema_lifecycle_prod.json` (355 bytes) and
  `sbe_fix_schema_lifecycle_testnet.json` (358 bytes) both fail with *"Illegal
  trailing comma before end of array: line 17"* — a `},` closing the last object of
  `deprecatedSchemas`. `sbe_schema_lifecycle_testnet.json` (2556 bytes) fails with
  *"Expecting ',' delimiter: line 39"* — two objects in `retiredSchemas` with no
  comma between them.
- **Implication for GLOBIN:** **This changed a decision.** The structured regime was
  designed on the assumption that a machine-readable source parses. Three of four do
  not, today. Two consequences follow. First, the refresh treats an unparseable
  structured source as `UNMEASURED` and reports it, rather than raising or falling
  back to a digest comparison that would mask it. Second, GLOBIN must not adopt a
  lenient parser to make these files load: a trailing comma is unambiguous but a
  missing one is not, and accepting both would mean accepting a file whose meaning
  cannot be recovered. Only the one file that parses is under field-level
  comparison, which is why `BINANCE_API_REALITY.md` states the proportion instead of
  describing the regime as though it covered four sources.

### S-11 — The former GitHub Pages derivatives documentation now redirects to a rendered application

- **Canonical location:** Binance, *Futures API documentation* (legacy host) —
  `https://binance-docs.github.io/apidocs/futures/en/`
- **Accessed:** 2026-08-19
- **Authority:** Primary, and measured: the response is 325 bytes of HTML whose
  entire body is `<meta http-equiv="refresh" content="0;url=https://developers.binance.com/docs/derivatives">`
  with a matching `<link rel="canonical">`. The target returns 138 bytes to a
  non-browser client.
- **Supports:** There is no fetchable text form of the derivatives, options,
  portfolio margin or margin documentation. The content is assembled client-side.
- **Implication for GLOBIN:** Establishing a derivatives fact would require either
  scraping a rendered page, which `SOURCE_POLICY.md` and ADR-0004 prohibit outright,
  or accepting a generated summary of one, which `SOURCE_POLICY.md` prohibits by
  name — *"Any generated summary of an API, including from a language model, used in
  place of reading the specification."* That prohibition earned itself during this
  phase: a summarizer asked for the COIN-M testnet WebSocket host returned
  `wss://demo-stream.binance.com`, which is the **Spot** demo stream host, presented
  with no indication of doubt. Every non-Spot product family is therefore recorded
  as an officially documented product whose endpoints, environments and auth rules
  are `UNKNOWN`, and the reason is recorded with them.

### S-12 — `MARGIN` and `LEVERAGED` are Spot symbol permissions, which is not the same as a margin product surface

- **Canonical location:** Binance, *Account and Symbol Permissions*, `enums.md`
  lines 15-19 —
  `https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/enums.md`
- **Accessed:** 2026-08-19
- **Authority:** Primary.
- **Supports:** The `permissions` enumeration contains `SPOT`, `MARGIN`,
  `LEVERAGED` and a long run of `TRD_GRP_*` values. `rest-api.md` shows them used as
  a filter on `GET /api/v3/exchangeInfo`.
- **Implication for GLOBIN:** A symbol being marked `MARGIN` on the Spot surface is
  evidence that margin trading exists; it is not evidence about the margin API's
  base URL, environments or authentication, which live under `/sapi` and are
  documented where S-11 cannot reach. The registry keeps the two apart: Cross Margin
  and Isolated Margin are recorded as documented product families with `UNKNOWN`
  surfaces, and the symbol permission is recorded where it was found, on Spot.

---

## Deferred, and to where

| Question | Phase |
|---|---|
| An admissible route to the derivatives, options, portfolio margin and margin documentation | 034 |
| A cadence for re-reading, and an accumulated change log rather than a pairwise diff | 034 |
| What GLOBIN may *do* in each environment class, and internal simulation | 035 |
| Whether an unmapped combination refuses at runtime, not merely in a query | 036 |
| Per-operation endpoint paths, methods, security types and weights | 037 |
| Which key type GLOBIN needs, and how a request is signed | 038 |
| Which grants a key was actually issued with | 039 |
| Documented request weights and order-count costs | 041 |
| Whether FIX and SBE are worth implementing at all | 047 |
