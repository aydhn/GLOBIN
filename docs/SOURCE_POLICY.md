# Source Policy

Which sources GLOBIN may rely on, in what order, and which are prohibited. The
decision behind this document is [ADR-0004](adr/0004-official-apis-only-no-scraping.md).

## Why this exists

A trading system's correctness depends on external behaviour it does not
control. When a contributor guesses at an endpoint or copies a parameter name
from a blog post, the resulting code frequently *looks* correct, passes review,
and fails against the real exchange — often silently, and often only under the
conditions that matter.

The rule that prevents this is simple: **behaviour that matters must be read
from the source that defines it.**

## Source hierarchy

Use the highest applicable tier. Never use a lower tier when a higher one covers
the question.

### Tier 1 — Authoritative and primary

The party that defines the behaviour, documenting its own behaviour.

| Domain | Authoritative source |
|---|---|
| Binance API behaviour | Binance Developer Documentation and the official `binance-spot-api-docs` specification repository |
| Binance SDK behaviour | The official `binance-connector-python` monorepo and its published packages |
| Binance historical data | Binance Public Data (`data.binance.vision`) and its official repository |
| Binance environments | Binance's own testnet and demo documentation |
| Third-party library behaviour | That project's own documentation, repository and published distribution metadata |
| Telegram bot behaviour | The official Telegram Bot API specification |
| Python language and standard library | The official Python documentation |

### Tier 2 — Supporting

Useful for orientation, never sufficient alone: upstream issue trackers, release
notes, changelogs, and source code of the library in question. A claim from
Tier 2 that contradicts Tier 1 loses.

### Tier 3 — Contextual only

Textbooks, papers and well-regarded technical writing may inform *design
reasoning* — a statistical method, an architectural pattern. They are never
evidence about how an external API behaves.

### Prohibited as a basis for implementation

- Blog posts, tutorials or forum answers describing exchange behaviour, when
  official documentation exists.
- Any generated summary of an API, including from a language model, used in
  place of reading the specification.
- Recollection. If you find yourself writing an endpoint from memory, stop and
  check it.

## Prohibited acquisition methods

GLOBIN must never:

- Scrape HTML from Binance or any exchange.
- Drive a browser to extract exchange data.
- Parse the DOM of exchange pages.
- Reverse-engineer undocumented endpoints used by the Binance web application.
- Depend on unofficial private front-end APIs.

This applies to documentation too: documentation ingestion (Phase 034) must use
official machine-readable resources rather than scraping rendered pages.

## Recording what you used

Every phase that relies on external behaviour records its sources in
`docs/research/phase_NNN_sources.md`. Each entry carries:

- **Source name**
- **Canonical location** — a stable URL
- **Accessed** — the date, in `YYYY-MM-DD` form
- **Authority** — `Primary` or `Secondary`, and why
- **Supports** — the specific technical claim it establishes
- **Implication for GLOBIN** — what the project must do differently because of it

Summarise. Do not copy documentation into the repository: copies go stale
invisibly, and the whole point is to know the source rather than a snapshot of
it. The format is enforced by `tests/test_documentation_contract.py`.

## When sources disagree or fall silent

- **Tier 1 wins** over any lower tier, always.
- **Two Tier 1 sources disagreeing** is a finding, not a nuisance. Record both,
  choose the more specific, and note the conflict.
- **No source answers the question.** Do not guess. Record the question as
  unresolved, name the phase that must resolve it, and design so the unknown is
  contained. The Phase 1 ledger ends with exactly such a table.

## Freshness

External behaviour changes. A source consulted in an earlier phase is evidence
about that date, not about today. Anything that governs live behaviour must be
re-verified when the phase depending on it is implemented — which is why access
dates are mandatory rather than decorative.
