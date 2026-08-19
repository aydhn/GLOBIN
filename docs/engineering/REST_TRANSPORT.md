# REST Transport

How GLOBIN sends a REST request to Binance, what it refuses to send, and — the
part this document exists for — what it does when it cannot tell whether a request
took effect.

The decisions behind it are
[ADR-0088](../adr/0088-phase-034-widens-to-deliver-the-rest-transport-substrate.md) and
[ADR-0089](../adr/0089-an-unknown-outcome-is-preserved-and-a-second-module-may-reach-a-socket.md).

---

## What Phase 034 is not

Stated first, because the surrounding phases own most of what a reader might
expect to find here.

| Not this phase | Whose it is | The extension point that waits for it |
|---|---|---|
| Request signing and authentication | 038 | `RestRequest.canonical_target()` renders exactly the span a signature covers |
| API key permission verification | 039 | `RequestSecurityIntent` is declared per request and gated before a credential is read |
| Clock synchronisation and drift | 040 | `TimeUnitPreference` records what was *asked for*; no offset is computed |
| Documented request weights | 041 | `rest-transport.toml` carries a weight for the three probes only |
| The rate-limit governor | 042 | `RateLimitReport` is extracted and typed; nothing acts on it |
| Retry, backoff and idempotency | 043 | `SideEffect` and `SendState` are recorded per request; **nothing retries** |
| The full error-code map | 044 | `ExchangeFault` carries the venue's code and message uninterpreted |
| WebSocket transport | 046 | — |
| SBE decoding | 047 | `SbeDecoder` is a `Protocol` with no implementation |
| An order engine | 100+ | — |

**No order is placed, no credential is read, and nothing at the venue changes.**
The only requests this phase can send are three public, unauthenticated GETs
declared in [`rest-transport.toml`](rest-transport.toml).

---

## The five-member outcome

A transport that reports *success* and *failure* has thrown away the state that
matters most to a trading system: the one where GLOBIN sent an order and does not
know what happened to it.

| Outcome | Means | Safe to retry? |
|---|---|---|
| `SUCCESS_CONFIRMED` | The venue answered, and the answer was success | n/a |
| `FAILURE_CONFIRMED` | It is known the operation did not take effect | Yes |
| `UNKNOWN` | Something may have happened and GLOBIN cannot tell what | **Never** |
| `NOT_SENT` | The bytes provably never left this process | Yes |
| `REJECTED_BEFORE_SEND` | GLOBIN's own gate declined | Fix the ask |

Binance documents the reason `UNKNOWN` has to exist. Of a 5XX response: *"It is
important to **NOT** treat this as a failure operation; the execution status is
**UNKNOWN**."* Of error `-1007`: *"Send status unknown; execution status
unknown"*, adding that it *"does not always mean that the request failed in the
Matching Engine."*

**The same response means different things to a read and to a write.** A 503 on a
price query is a confirmed failure — nothing was at stake and the caller may ask
again. A 503 on an order placement is ambiguous, because the matching engine may
have accepted it. `classify()` therefore takes the side effect as an input, and a
read-only request can never return `UNKNOWN` from it.

### What is *not* ambiguous, and why that matters

403, 418 and 429 are refusals at the edge — a WAF violation, an IP ban and a
rate-limit rejection — so all three are **confirmed failures even for a write**.
Marking them ambiguous "to be safe" would be unsafe: Phase 043 never retries an
ambiguous outcome, so an ordinary rate-limit rejection, the one failure that is
always retryable, would become permanently unretryable.

### Why nothing retries

There is no retry loop, no backoff and no replay in this phase, and no parameter
that would produce one. Phase 043 owns retry and inherits one rule from here: **an
`UNKNOWN` outcome is never replayed.** Replaying a mutating request whose fate is
unknown is how one order becomes two.

`tests/contract/test_rest_contract.py` asserts the absence against the source, and
`tests/unit/test_rest_transport.py` asserts that one `send()` produces exactly one
connection attempt.

---

## Endpoint resolution

`globin.domain.rest_endpoint` is the only thing in GLOBIN that turns Phase 033's
registry into an address. There is no table of base URLs, no `if family == ...`
and no default host anywhere in the package —
`tests/architecture/test_api_reality_discipline.py` fails if a venue host is
spelled in a module at all.

Ten gates, in order, each refusing before the next is reached:

1. the product is in the registry;
2. its REST surface is documented `supported`;
3. this environment is documented `supported` for it;
4. the registry records at least one REST endpoint for the pair;
5. at least one such endpoint is itself `supported`;
6. one of those documents the capability asked for;
7. one of *those* accepts a credential, when the intent needs one;
8. a current SBE schema exists, when SBE is asked for;
9. the chosen endpoint's evidence is not **stale**;
10. the chosen endpoint's host agrees with its environment.

### The three substitutions that are structurally impossible

**Testnet never becomes production.** The only source of candidates is
`endpoints_for(family, environment, protocol)`, which filters on environment
*before* returning. There is no branch in which a production URL is reachable from
a testnet request, because production endpoints are never in the candidate set.

**Demo never becomes testnet.** Same mechanism; Phase 033 files them as distinct
environments with distinct host markers.

**A market-data host never serves an order.** The venue publishes an
unauthenticated market-data-only host, recorded with capabilities exactly
`["market_data"]`. A caller names the capability it needs, and an endpoint that
does not list it is not a candidate.

A refusal **carries no endpoint at all** — `EndpointResolution` refuses that
combination at construction — so a caller that ignored the outcome finds nothing to
misuse.

### Alternates, and why nothing fails over

Phase 033 records seven production Spot REST endpoints. The resolver returns the
role of the one it chose and the URLs of the rest, and **acts on neither**. A
resolution is fixed for the life of one request. Replaying an ambiguous mutating
request against a second host is the same duplicate-order failure as retrying it
against the first.

### What resolves today

| Product family | REST surface | Resolves |
|---|---|---|
| Spot | `supported` | production, demo, testnet |
| Every other family | `unknown` | nothing |

Every count in this document is recomputed from the code and the registry by
`tests/contract/test_rest_contract.py`, so none of them can drift from what the
package actually does:

| What | Count |
|---|---|
| Outcome members | 5 |
| Resolution outcomes | 10 |
| Body shapes | 9 |
| Product families recorded | 13 |
| Families whose REST surface resolves | 1 |
| Families that refuse | 12 |
| Product-and-environment pairs surveyed | 24 |
| Pairs that resolve | 3 |
| Declared public probes | 3 |
| Self-test checks | 8 |

Twelve of the thirteen recorded families refuse. That is not a gap: the venue's
derivatives documentation is a client-rendered application with no admissible
route, [`SOURCE_POLICY.md`](../SOURCE_POLICY.md) forbids both scraping it and
accepting a generated summary, and `unknown` is the honest answer. A transport that
resolved one anyway would be inventing an endpoint.

```bash
.venv\Scripts\globin.exe rest resolve --family usds_m_futures --environment production
```

exits `14` and names the recorded status.

---

## Staleness, and the other half of this phase

Gate 9 above is where Phase 034's two halves meet. A REST endpoint resting on a
source past the re-check interval its regime declares **cannot be resolved** —
`ResolutionStatus.SOURCE_STALE`, before any socket opens. Phase 033 recorded *when*
each document was read and nothing consumed the date; the cadence that turns it
into a decision is
[`DOCUMENTATION_INGESTION.md`](DOCUMENTATION_INGESTION.md).

---

## Content negotiation

Every value below was read from the venue's own documentation, is recorded with its
citation in [`rest-transport.toml`](rest-transport.toml), and is compared against
the package's constants in both directions by
`tests/contract/test_rest_contract.py`.

| Header | Value | Note |
|---|---|---|
| `Accept` | `application/json` | The default |
| `Accept` | `application/sbe` | **Offered alone**, never beside JSON |
| `X-MBX-SBE` | `<ID>:<VERSION>` | Character for character what Phase 033's `SchemaVersion.label` already rendered |
| `X-MBX-TIME-UNIT` | `MICROSECOND` | Singular, and the **only** documented value |

**There is no millisecond header, and that is a finding rather than an omission.**
The documentation states responses are *"in milliseconds by default"* and never
lists a header value that selects them. `SOURCE_POLICY.md` forbids inventing a
parameter value, so `TimeUnitPreference.MILLISECONDS` sends **no header at all**:
asking for the documented default is the same act as not asking.

**The SBE `Accept` names one media type, and that is a security decision.** The SBE
FAQ documents that an `Accept` offering both `application/sbe` and
`application/json` *"will fall back to JSON"* when the schema is unsupported. That
is a silent downgrade: GLOBIN would hold a JSON body while its own record said SBE
— an optimistic acceptance of a capability that was not available. Offering one
media type deletes the branch rather than handling it.

### Where SBE stops

Phase 034 negotiates SBE, gates it on the registry's published schema lifecycle,
and carries a binary answer in an opaque `SbeEnvelope` that no JSON parser ever
sees. **It decodes nothing.** `globin.ports.rest.SbeDecoder` is an interface with
no implementation, because whether decoding SBE is worth its schema tooling is the
question Phase 047 was created to answer.

SBE resolves in production and fails closed in testnet, because the registry
publishes a current `spot_sbe` schema for one and not the other.

---

## Response decoding

Nine shapes, told apart **before** anything tries to use the body:

`EMPTY` · `OBJECT` · `ARRAY` · `SCALAR` · `MALFORMED_JSON` · `HTML` · `TEXT` ·
`BINARY` · `UNEXPECTED_CONTENT_TYPE`

The two that earn the list are the firewall's HTML page and the SBE payload. Both
arrive on an endpoint that answers JSON by default, and feeding either to a JSON
parser produces an exception about column one of a document nobody meant to send.

**A venue error is not a transport failure.** A body carrying
`{"code": ..., "msg": ...}` over a completed exchange means the venue answered and
refused — an `ExchangeError`, not a `TransportError`. Those two classes have sat in
[`errors.py`](../../src/globin/errors.py) since Phase 005 with the note *"Phases
033-048 introduce the callers"*. This is that phase. Collapsing them is how a
system convinces itself an order failed when it did not.

---

## Security boundary

| Rule | How it is held |
|---|---|
| TLS verification cannot be disabled | `secure_context()` takes **no arguments**; a contract test proves no `CERT_NONE` anywhere in the package |
| Only one module reaches outward | `tests/architecture/test_library_discipline.py` names exactly two socket-capable modules, one per direction |
| The transport cannot choose a host | `send()` is handed a resolution and never sees the registry |
| One transport, one environment | Bound at construction; a resolution from elsewhere is refused before a socket opens |
| A probe cannot become a write | The probe path hardcodes `READ_ONLY` and `PUBLIC`; there is no parameter for either |
| No credential is read on a probe path | The intent is `PUBLIC`, so nothing consults the secret store |
| No request can be redirected through a proxy | **There is no proxy path at all** — nothing calls `set_tunnel` and nothing reads a proxy setting from the environment, so the host reached is exactly the host resolved |

### What a diagnostic record may contain

Every field is GLOBIN's own vocabulary or a number, plus the resolved **hostname**.
There is no field for a URL, a query string, a header value or a body — so
redaction downstream is a second line of defence over a record that already carries
nothing to redact. `tests/integration/test_rest_transport_end_to_end.py` drives a
request carrying `signature` and `apiKey` parameters and asserts neither value
appears anywhere in the exchange.

Response bodies are bounded at 8 MiB and never logged beyond 512 bytes. A body at
the cap is a **failure**, never a truncation: a half-read JSON document that
happened to parse would be the worst possible outcome.

---

## Connection lifecycle

`http.client.HTTPSConnection` behind a bounded pool. No new dependency was adopted:
the wheel survey records `binance-common` against Phase 045, and adopting a second
HTTP stack now would leave two in the tree.

- explicit `open()` and `close()`, both idempotent, plus a context manager;
- bounded by connection count, per-connection use count and keep-alive age;
- a connection that raised, or whose body exceeded the cap, is **discarded rather
  than pooled** — returning it would corrupt the *next* request rather than this
  one, which is the hardest kind of bug to trace back here.

**Connecting is an explicit step.** `http.client` connects lazily inside
`request()`, which would fold a DNS failure and a half-written request into one
exception and leave GLOBIN unable to say whether any bytes left. Calling
`connect()` separately is what makes `NOT_SENT` an honest answer.

`TimeoutPolicy` declares four bounds against a client that applies one, and
`honoured()` says which are actually enforced — the Phase 024 rule that a
measurement not taken is never reported as taken.

---

## Public probes

Three, all documented security `NONE`:

```bash
.venv\Scripts\globin.exe rest ping --family spot --environment testnet
```

```bash
.venv\Scripts\globin.exe rest server-time --family spot --environment testnet
```

**The verb is the opt-in.** There is no `--network` flag to forget, which is the
shape `venue check` and `venue refresh` already use: a command that only makes
sense over a network says so in its name. A configuration key gating them would be
a mechanism with no caller — nothing in GLOBIN runs long enough to consult one.

Before the connection opens, the command prints what it is about to do, names the
environment, and says the request is public and unauthenticated.

**`EvidenceKind.OBSERVED` is still unwritable.** GLOBIN now reaches the venue,
which is exactly when that rule stops being free. A probe result is evidence about
a *run*; it never edits the registry.

---

## Offline and network tests

| | |
|---|---|
| The whole status and body matrix | A real local HTTP server, `loopback`-marked. The guard in `tests/conftest.py` narrows rather than lifts, so a mistake reaching Binance still fails |
| DNS, TLS, refused, reset, malformed status line | A connection factory that raises — no server can produce these |
| Resolution, encoding, outcome, contract | Pure; no socket anywhere |
| Reaching Binance | `tests/integration/test_rest_probe_external.py`, `external`-marked and excluded by **every** quality selection |

```bash
python -m pytest -q -m external
```

CI runs none of it. Nothing in `full` reaches a network.

---

## Evidence

```bash
.venv\Scripts\globin.exe rest evidence
```

writes `.globin/rest/rest-manifest.json`: the registry digest, the contract's
observation date, the resolution survey, the source freshness report, the
eight-check self-test, and the declared probes. Paths and timings are normalised,
so an unchanged tree digests identically.

A machine that ran no probe records `probe_results: "unmeasured"` — the same answer
`drift` gives for an unrecorded baseline. Nothing was established, which is not the
same as nothing being wrong.

```bash
.venv\Scripts\globin.exe rest selftest
```

recomputes the outcome classification from the declared contract, compares every
negotiation constant in both directions, and asserts the prohibitions are still
prohibited — on a machine with no network and no pytest.

---

## Exit codes

No twenty-sixth exit code was added. **26 stays free.**

| Code | When |
|---|---|
| `0` | Resolved, or the self-test passed, or the probe confirmed success |
| `1` | A self-test check failed, or a probe did not confirm success |
| `3` | A committed document is absent, so nothing was established |
| `14` | The ask cannot be resolved — which is what `CONFIGURATION_INVALID` already means |
