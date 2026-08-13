# ADR-0003 — Zero-budget runtime and open-source dependency policy

## Status

Accepted — Phase 001.

## Context

A trading system that depends on paid services acquires a recurring cost that
must be earned back before the first unit of profit. Worse, it acquires
external failure modes: an expired card, a quota change or a deprecated tier
can halt trading. For a personally operated system, that fragility is not worth
the convenience.

There is also a distinction that is easy to blur. The tools used to *develop*
GLOBIN are not the same as the services GLOBIN *depends on at runtime*.

## Decision

**The GLOBIN runtime must depend entirely on free components.** This is encoded
as `PAID_RUNTIME_SERVICES_ALLOWED = False` and enforced two ways: by contract
test, and by `tests/test_packaging_contract.py`, which asserts that the runtime
dependency list in `pyproject.toml` is empty in Phase 1 and therefore cannot
grow without a deliberate edit to the test.

Permitted: the Python standard library, free and open-source Python packages,
officially documented Binance APIs and SDKs, Binance's public data resources,
the Telegram Bot API, local files and databases, open-source machine learning
and optimisation libraries, and local GPU acceleration.

Prohibited as runtime dependencies: hosted large-language-model APIs, paid
market data, paid social media APIs, paid RPC providers, paid databases,
message queues, monitoring services, and cloud compute.

**Development tooling is explicitly out of scope for this rule.** External
coding agents and services may be used to build GLOBIN. They must never be
required for it to run.

## Consequences

- Every proposed dependency needs a licence and cost review. Phase 014 defines
  that process.
- Some capabilities will be unavailable or must be built rather than bought.
  That cost is accepted deliberately.
- Local storage, local compute and local scheduling replace their hosted
  equivalents, which is why the data platform and orchestration bands are
  substantial.
- A future decision to accept a paid runtime dependency requires a superseding
  ADR and an update to the packaging contract test.
