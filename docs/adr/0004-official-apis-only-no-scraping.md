# ADR-0004 — Official documented interfaces only; no scraping

## Status

Accepted — Phase 001.

## Context

Exchange data can be obtained by scraping web pages or by calling the private
endpoints a web front end uses internally. Both are tempting because they
sometimes expose information faster or more conveniently than the public API.

Both are also unacceptable here. Private front-end endpoints carry no
compatibility guarantee and can change without notice, turning a working system
into a silently broken one. Scraping is brittle by construction, frequently
conflicts with terms of service, and produces data of unknown provenance — which
is fatal for a system whose research validity depends on knowing exactly what it
observed and when.

## Decision

**GLOBIN obtains data only through officially documented interfaces.** This is
encoded as `WEB_SCRAPING_ALLOWED = False`.

Prohibited: HTML scraping, browser automation against exchange pages, DOM
parsing to extract exchange data, reverse-engineering undocumented Binance web
application endpoints, and any dependence on unofficial private front-end APIs.

Permitted: documented REST and WebSocket APIs, documented SDKs and connectors,
documented streams, and legitimate downloadable public datasets such as Binance
Public Data.

The source hierarchy is defined in `docs/SOURCE_POLICY.md`. Official Binance
documentation is authoritative for Binance behaviour; upstream project
documentation is authoritative for third-party libraries.

## Consequences

- Some data visible in the Binance web interface may be unavailable to GLOBIN.
  That is accepted; unavailable is preferable to unreliable.
- Data acquisition is stable and auditable, and every dataset has recorded
  provenance (Phase 108).
- Documentation ingestion must itself use official machine-readable sources
  rather than scraping rendered documentation pages (Phase 034).
- Credentials, including the Telegram bot token, are secrets subject to the
  handling rules in Phase 015 and Phase 028, and must never be committed.
