# Phase 001 — Research Source Ledger

Every architectural claim made in Phase 1 documentation traces to an entry
below. Entries are summaries written for GLOBIN's purposes; documentation text
is not copied into this repository.

**Ledger conventions**

- `Authority: Primary` means the vendor or upstream project publishing its own
  behaviour. `Secondary` means anything else.
- Where a fact could not be verified from a primary source in this phase, the
  entry says so explicitly and names the phase that must verify it. Unverified
  facts are never written into architecture documents as settled.
- All accesses were performed on the date recorded in each entry.

---

## Binance — platform, environments and limits

### S-01 — Binance Developer Documentation portal

- **Canonical location:** https://developers.binance.com/en/docs/
- **Accessed:** 2026-08-14
- **Authority:** Primary — vendor-official documentation portal.
- **Supports:** The documented product families are Spot, Margin, USDⓈ-M
  Futures, COIN-M Futures, Options, Portfolio Margin, Wallet and Algo Trading.
  The portal treats "Environments" and "Rate Limits and Reliability" as
  first-class production-readiness topics rather than footnotes.
- **Implication for GLOBIN:** Confirms the product scope in ADR-0002 is
  expressible against officially documented surfaces. The portal is a
  JavaScript-rendered application, so automated retrieval must target the
  underlying Markdown repositories or the machine-readable index rather than
  the rendered pages.

### S-02 — Binance machine-readable documentation index

- **Canonical location:** https://developers.binance.com/docs/llms.txt
- **Accessed:** 2026-08-14
- **Authority:** Primary — vendor-published index intended for automated
  consumption, alongside an `llms-full.txt` variant and an "Agent Native"
  documentation section.
- **Supports:** Binance publishes an index designed for machine and agent
  consumption of its documentation.
- **Implication for GLOBIN:** Phase 034 should build documentation ingestion
  and change tracking on this index rather than scraping rendered HTML, which
  would violate ADR-0004. Note that the index returned is a navigation summary
  rather than a complete endpoint catalogue; its actual coverage must be
  assessed in Phase 034 before being relied upon.

### S-03 — Binance Spot API documentation repository

- **Canonical location:** https://github.com/binance/binance-spot-api-docs
- **Accessed:** 2026-08-14
- **Authority:** Primary — the vendor's own specification repository, which
  states that streams, endpoints, parameters and payloads described there are
  official and supported.
- **Supports:** The Spot surface is specified across REST API, WebSocket API,
  WebSocket streams, user data streams, FIX API, SBE market data streams, plus
  enumerations, filters and error definitions.
- **Implication for GLOBIN:** This repository, not the rendered portal, is the
  authoritative and automation-friendly source for Phases 033-048. It also
  confirms FIX and SBE exist as documented interfaces worth the assessment
  scheduled in Phase 047.

### S-04 — Binance Spot REST API: rate limits and error semantics

- **Canonical location:** https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/rest-api.md
- **Accessed:** 2026-08-14
- **Authority:** Primary — vendor specification.
- **Supports:** Three rate limit types exist (`REQUEST_WEIGHT`, `ORDERS`,
  `RAW_REQUESTS`), published in the `rateLimits` array of `exchangeInfo`.
  Usage is reported back in `X-MBX-USED-WEIGHT-(intervalNum)(intervalLetter)`
  and `X-MBX-ORDER-COUNT-(intervalNum)(intervalLetter)` response headers.
  HTTP 429 signals a breach and carries `Retry-After`; HTTP 418 signals an
  automatic IP ban escalating from two minutes to three days. Critically, the
  specification states that a 5XX response must **not** be treated as a failed
  operation — the execution status is unknown and may have succeeded.
- **Implication for GLOBIN:** This is the primary evidence behind two
  architecture principles. Rate limiting becomes a proactive, header-driven
  concern (Phases 041-042) rather than a reaction to rejection. And order
  execution must be designed around indeterminate states resolved by querying
  authoritative state (Phases 086 and 095), never by assuming failure on
  timeout.

### S-05 — Binance Demo Mode for Spot trading

- **Canonical location:** https://developers.binance.com/docs/binance-spot-api-docs/demo-mode/general-info
- **Accessed:** 2026-08-14
- **Authority:** Primary — vendor documentation.
- **Supports:** Demo Mode runs against `https://demo-api.binance.com/api`,
  `wss://demo-ws-api.binance.com/ws-api/v3` and `wss://demo-stream.binance.com/ws`.
  Keys are issued separately through the demo account portal and are distinct
  from live credentials. Coverage documented here is **Spot only**. Binance
  explicitly warns that realistic market data is not real market data and that
  demo success does not imply live success.
- **Implication for GLOBIN:** Demo Mode is a distinct environment class, not a
  synonym for testnet. Its Spot-only coverage is direct evidence that a single
  universal non-production endpoint does not exist, which is the foundation of
  ADR-0006 and Phase 036.

### S-06 — Binance Spot Test Network

- **Canonical location:** https://testnet.binance.vision/
- **Accessed:** 2026-08-14
- **Authority:** Primary — vendor-operated test network.
- **Supports:** Spot Testnet is reachable at `https://testnet.binance.vision/api`
  with streams at `wss://stream.testnet.binance.vision/ws`. Keys are issued
  through the testnet dashboard and support HMAC-SHA-256, RSA and Ed25519. All
  funds are virtual and cannot be transferred. The network is reset roughly
  monthly without advance notice. Only `/api` endpoints are available —
  `/sapi` endpoints are unsupported. Rate limits and filters mirror production.
- **Implication for GLOBIN:** Decisive for ADR-0006. Because Margin and Wallet
  functionality lives under `/sapi`, the Spot Testnet cannot exercise those
  products at all. Combined with S-05, this proves non-production coverage is
  genuinely per-product. Furthermore, monthly resets mean testnet state is
  ephemeral: no durable research or reconciliation history may be founded on
  it (relevant to Phases 095 and 299).

### S-07 — Binance official Python SDK monorepo

- **Canonical location:** https://github.com/binance/binance-connector-python
- **Accessed:** 2026-08-14
- **Authority:** Primary — the vendor's own connector project.
- **Supports:** The connector is no longer a single package. It is a monorepo
  publishing roughly twenty-five independent PyPI distributions, including
  `binance-sdk-spot`, `binance-sdk-margin-trading`,
  `binance-sdk-derivatives-trading-usds-futures`,
  `binance-sdk-derivatives-trading-coin-futures`,
  `binance-sdk-derivatives-trading-options`,
  `binance-sdk-derivatives-trading-portfolio-margin`,
  `binance-sdk-derivatives-trading-portfolio-margin-pro`,
  `binance-sdk-wallet` and `binance-sdk-algo`. Python 3.10 or later is
  required, and a migration guide documents the move from the older unified
  connector.
- **Implication for GLOBIN:** Strong independent corroboration of ADR-0006 —
  Binance itself models products as separately versioned units with their own
  lifecycles. GLOBIN's adapter layer (Phases 065-080) should mirror that
  separation rather than inventing a single monolithic client. The per-product
  packaging also means dependency selection in Phases 020-021 must be
  product-scoped, installing only what each enabled product needs.

### S-08 — Binance public historical market data

- **Canonical location:** https://github.com/binance/binance-public-data
- **Accessed:** 2026-08-14
- **Authority:** Primary — vendor-published dataset and tooling, served from
  `https://data.binance.vision/`.
- **Supports:** Free bulk historical data covering Spot, USD-M Futures and
  COIN-M Futures across all symbols, including klines, trades and aggregate
  trades, with kline intervals from one second upward. Files are ZIP archives
  partitioned daily and monthly, each accompanied by a `.CHECKSUM` file for
  SHA-256 verification. No API key or registration is required. Spot data from
  1 January 2025 onward carries microsecond timestamps.
- **Implication for GLOBIN:** Satisfies the historical data requirement within
  the zero-budget policy (ADR-0003) using an official source (ADR-0004). Two
  consequences for later phases: checksum verification is mandatory before any
  archive is trusted (Phase 053), and the microsecond timestamp change is a
  schema discontinuity that Phase 098 must handle explicitly rather than
  assume away.

---

## Machine learning, optimisation and acceleration

### S-09 — PyTorch distribution metadata

- **Canonical location:** https://pypi.org/pypi/torch/json
- **Accessed:** 2026-08-14
- **Authority:** Primary — the upstream project's own published distribution
  metadata.
- **Supports:** Current version 2.13.0, requiring Python 3.10 or later, with
  classifiers declaring support through Python 3.14. Licensing is a permissive
  combination including Apache-2.0, BSD and MIT terms.
- **Implication for GLOBIN:** PyTorch does not constrain the interpreter choice
  on this host and is licence-compatible with the zero-budget policy. Windows
  CUDA wheel selection is installation-specific and must be verified on the
  actual machine in Phases 023-024 rather than assumed from metadata.

### S-10 — XGBoost GPU documentation

- **Canonical location:** https://xgboost.readthedocs.io/en/stable/gpu/index.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — upstream project documentation.
- **Supports:** GPU acceleration is enabled through the `device` parameter set
  to `cuda`, optionally with a device ordinal. A sufficiently recent CUDA
  toolkit is required. Multi-GPU scaling is offered through Dask and Spark
  integrations that are irrelevant to a single-host deployment.
- **Implication for GLOBIN:** XGBoost is a credible GPU-accelerated candidate
  for Phase 182, but the older `tree_method="gpu_hist"` idiom is superseded and
  must not be used. Actual benefit must be measured on this host, per the
  evidence-driven acceleration principle.

### S-11 — XGBoost distribution metadata

- **Canonical location:** https://pypi.org/pypi/xgboost/json
- **Accessed:** 2026-08-14
- **Authority:** Primary — upstream distribution metadata.
- **Supports:** Current version 3.4.0 requires **Python 3.12 or later**, and is
  Apache-2.0 licensed. NCCL is declared as a dependency only on Linux.
- **Implication for GLOBIN:** This is the strictest interpreter floor among all
  libraries scheduled for later phases, and is the direct reason
  `requires-python` is set to `>=3.12` in Phase 1 rather than a lower value.
  Choosing the floor now avoids a breaking change when Phase 182 arrives. The
  Linux-only NCCL dependency is a reminder that distributed GPU features are
  not uniformly available on Windows.

### S-12 — LightGBM distribution metadata and GPU support

- **Canonical location:** https://pypi.org/pypi/lightgbm/json
- **Accessed:** 2026-08-14
- **Authority:** Primary — upstream distribution metadata and project
  documentation.
- **Supports:** Current version 4.7.0 requires Python 3.10 or later. Published
  wheels cover CPU use on Windows and Linux, but CUDA support requires building
  from source, and the project states that **the CUDA version is not supported
  for macOS and Windows users**. The alternative GPU backend is OpenCL-based
  and also requires a source build.
- **Implication for GLOBIN:** Primary evidence for the evidence-driven
  acceleration principle. The same library offers different acceleration
  availability depending on operating system, so a blanket policy of moving
  machine learning work to CUDA would be incorrect on the target Windows host.
  Phase 182 must treat LightGBM as CPU-only unless a source build is
  explicitly justified and verified.

### S-13 — Optuna

- **Canonical location:** https://pypi.org/pypi/optuna/json
- **Accessed:** 2026-08-14
- **Authority:** Primary — upstream distribution metadata, corroborated by the
  project documentation at `https://optuna.readthedocs.io/en/stable/`.
- **Supports:** Current version 4.9.0, MIT licensed, requiring Python 3.9 or
  later. The project documents pluggable samplers and pruners and supports
  persistent study storage through a relational backend, which enables
  resumable and parallel optimisation.
- **Implication for GLOBIN:** Suitable for Phases 209-224 within the
  zero-budget policy. Persistent local storage means optimisation studies can
  survive restarts, which matters for the long-running orchestration model.

### S-14 — Gymnasium

- **Canonical location:** https://pypi.org/pypi/gymnasium/json
- **Accessed:** 2026-08-14
- **Authority:** Primary — upstream distribution metadata.
- **Supports:** Current version 1.3.0, MIT licensed, requiring Python 3.10 or
  later. Provides the standard API for reinforcement learning environments.
- **Implication for GLOBIN:** Establishes the environment interface that the
  trading environment in Phase 194 must implement, which in turn is what makes
  third-party algorithm implementations usable without custom glue.

### S-15 — Stable-Baselines3

- **Canonical location:** https://pypi.org/pypi/stable-baselines3/json
- **Accessed:** 2026-08-14
- **Authority:** Primary — upstream distribution metadata.
- **Supports:** Current version 2.9.0, MIT licensed, requiring Python 3.10 or
  later. Provides PyTorch implementations of standard reinforcement learning
  algorithms including PPO.
- **Implication for GLOBIN:** Supplies the algorithm implementations for Phases
  201-202 at zero cost. Because it is PyTorch-backed, its device placement is
  governed by the same evidence requirement as any other accelerated workload;
  policy-gradient training on small networks is frequently CPU-favourable and
  must be benchmarked in Phase 205 rather than assumed.

### S-16 — TA-Lib Python wrapper

- **Canonical location:** https://pypi.org/pypi/ta-lib/json
- **Accessed:** 2026-08-14
- **Authority:** Primary — upstream distribution metadata.
- **Supports:** Current version 0.7.1, BSD 2-Clause licensed, requiring Python
  3.9 or later. The wrapper explicitly requires the underlying native TA-Lib C
  library to be installed separately before the Python package can be used.
- **Implication for GLOBIN:** The native dependency is a real Windows
  provisioning problem, which is why Phase 025 exists as a dedicated phase
  rather than being folded into general dependency installation. Phase 114 must
  provide a fallback path so that indicator computation is not hard-blocked if
  the native library cannot be provisioned on a given host.

---

## Operations

### S-17 — Telegram Bot API

- **Canonical location:** https://core.telegram.org/bots/api
- **Accessed:** 2026-08-14
- **Authority:** Primary — vendor-official API specification.
- **Supports:** Bot API version 10.2, released 14 July 2026. Methods are called
  at `https://api.telegram.org/bot<token>/METHOD_NAME`. Both long polling via
  `getUpdates` and webhook delivery are supported, but the two are mutually
  exclusive for a given bot.
- **Implication for GLOBIN:** Satisfies the operator communication requirement
  at zero cost (Phases 273-279). Long polling is the appropriate choice for a
  local Windows host because webhooks would require a publicly reachable
  inbound endpoint, which the deployment model does not provide. The bot token
  is a credential and falls under the secret-handling rules in ADR-0004 and
  Phase 028.

---

## Facts deliberately left unverified in Phase 1

The following are relevant but were not settled here, because settling them
requires either account-specific state or work belonging to a later phase.
They are recorded so that no later phase mistakes silence for confirmation.

| Question | Why unresolved | Phase that must resolve it |
|---|---|---|
| Which non-production environments exist for Margin, Options, Portfolio Margin and Portfolio Margin Pro | Coverage is documented per product and could not be confirmed uniformly from primary sources in this phase | 035-036 |
| Whether this specific account holds the permissions for each product family | Account-specific; requires live credential inspection | 039, 065 |
| Which CUDA build actually installs and performs well on this host | Requires the physical machine and measurement, not metadata | 023-024 |
| Whether the FIX and SBE interfaces provide material value here | Requires the transport layer to exist first | 047 |
| Whether packaging builds correctly from `pyproject.toml` | No build is executed in Phase 1 by design | 017-032 |
