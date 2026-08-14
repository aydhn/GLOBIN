# Architecture Principles

Durable technical reasoning for GLOBIN. Single decisions live in
[`adr/`](adr/); this document holds the principles that shape many decisions.

Each principle states what is true, why it is true, and what it forces the
implementation to do. Where a principle rests on evidence, the evidence is cited
from [`research/phase_001_sources.md`](research/phase_001_sources.md).

---

## 1. Test environments are product-specific

**The claim.** Binance does not have one test environment. It has several, and
their coverage differs per product.

**The evidence.** Demo Mode runs on production infrastructure with virtual
balances and is documented for Spot only (S-05). Spot Testnet is separate
infrastructure with separate credentials, resets roughly monthly without notice,
and serves only `/api` endpoints — `/sapi` is unsupported, so Margin and Wallet
cannot be exercised there at all (S-06). Futures Testnet is a third environment
with its own base URLs. Binance's own SDK ships as roughly twenty-five
independent per-product packages (S-07).

**What it forces.** Product and environment are independent dimensions resolved
through an explicit capability matrix (ADR-0006, Phase 036). Paper trading is a
composition of per-product decisions, not a global mode. When the matrix has no
entry for a requested combination, the operation is **refused** — never silently
downgraded, and never allowed to fall through to production. That refusal rule is
the property that keeps an unmapped combination away from real capital.

---

## 2. A failed request does not prove a failed operation

**The claim.** When a request times out or returns a server error, the state of
the operation is *unknown*. It may have succeeded.

**The evidence.** The Binance REST specification states explicitly that a 5XX
response must not be treated as a failed operation, that execution status is
unknown, and that the caller must query order status to find out (S-04).

**What it forces.** Order handling is built around indeterminate states rather
than a success/failure binary. The order state machine (Phase 084) includes
explicitly unknown states. Resolution happens by querying authoritative exchange
state (Phase 086), never by assumption. Client order identifiers make retries
idempotent (Phase 083), and continuous reconciliation repairs divergence
(Phase 095).

The tempting mistake — treating a timeout as failure and retrying — produces
duplicate positions. The opposite mistake produces phantom ones. Only
reconciliation against the exchange resolves it.

---

## 3. Rate limits are a correctness concern

**The claim.** Rate limiting is not politeness. Exceeding limits produces bans
that stop trading, potentially while positions are open.

**The evidence.** Three limit types exist — `REQUEST_WEIGHT`, `ORDERS`,
`RAW_REQUESTS` — with per-endpoint weights published in `exchangeInfo`. Usage is
reported in `X-MBX-USED-WEIGHT-*` and `X-MBX-ORDER-COUNT-*` response headers.
HTTP 429 signals breach with a `Retry-After` header; HTTP 418 signals an IP ban
escalating from two minutes to three days (S-04).

**What it forces.** Limiting is **proactive**, driven by the returned usage
headers, rather than reactive to rejection (Phases 041-042). Endpoint weights are
registered rather than guessed. Backoff respects `Retry-After`. Critically, order
cancellation and risk-reducing operations must retain budget: running out of
request weight while needing to close a position is a risk event, not an
inconvenience.

---

## 4. Prediction is probabilistic

**The claim.** No technique in this system — technical analysis, supervised
learning, reinforcement learning, or any ensemble — can guarantee a correct or
profitable prediction.

**What it forces.** The objective is a *measurable probabilistic edge after
realistic costs and out-of-sample validation*. Every report the system produces
must describe results in those terms. Models output calibrated probabilities
(Phase 187), not verdicts. Backtests that ignore fees, spread, slippage, funding
or borrow costs are treated as defects rather than approximations
(Phases 148-153). Position sizing derives from confidence and volatility, never
from certainty.

Any documentation, log line, alert or report implying certainty is a defect,
because downstream decisions — especially sizing — are made on the basis of
stated confidence.

---

## 5. Acceleration must be evidence-driven

**The claim.** The GPU is not universally faster. Whether it helps depends on
the workload, the data size, and the platform.

**The evidence.** LightGBM's CUDA backend is **not supported on Windows** at all,
and its OpenCL backend requires a source build (S-12). XGBoost supports CUDA via
its `device` parameter but declares NCCL only on Linux (S-10, S-11). PyTorch
supports Windows CUDA but the benefit depends entirely on model size and batch
shape (S-09). Policy-gradient reinforcement learning on small networks is
frequently CPU-favourable.

**What it forces.** No workload is placed on the GPU by assumption. Phase 024
builds a benchmark harness, and Phase 205 benchmarks reinforcement learning
specifically. Device placement is a measured decision recorded per workload.
Many indicator and dataframe transformations will remain faster on vectorised
CPU code, and that is a legitimate outcome rather than a failure to optimise.

The failure mode this prevents is real: moving everything to CUDA on a machine
where one key library silently cannot use it, and paying transfer overhead for
nothing.

---

## 6. Point-in-time correctness is structural

**The claim.** Research may only ever see what was actually knowable at the
time. Lookahead is not a bug to be found later; it must be impossible by
construction.

**What it forces.** Observation time is modelled separately from event time
(Phase 101). Joins are as-of joins respecting knowledge boundaries (Phase 102).
Datasets are immutable and versioned so results can be re-derived exactly
(Phase 103). Preprocessing is fitted inside folds only (Phase 180). Cross
validation is purged and embargoed (Phase 163).

Leakage is uniquely dangerous because it does not degrade results — it improves
them. A leaked feature makes a backtest look better, which means the failure
mode is indistinguishable from success until real capital is committed.

---

## 7. Autonomy operates inside fixed bounds

**The claim.** A system that can modify its own constraints has no constraints.

**What it forces.** Constraints are tiered: immutable ceilings, governed policy
limits, and tunable parameters (ADR-0008). Optimisation may search only the
third tier. Ceilings are enforced at the last point before order submission, so
a defect anywhere upstream still cannot breach them (Phase 253). Promotion of
any autonomous candidate requires passing evidence gates that the system itself
cannot weaken (ADR-0007, Phase 237). Every autonomous change leaves an audit
trail (Phase 236).

Adaptation that relaxes a binding constraint almost always improves a backtest,
which is exactly why the ability must not exist.

---

## 8. Reliability outranks performance

**The claim.** At tens of trades per hour on a single consumer machine,
microseconds are irrelevant and uptime is everything.

**What it forces.** Design effort goes to crash recovery, state persistence,
reconnection, watchdogs and reconciliation (Phases 257-272) rather than latency
tuning. The system must survive disconnections, restarts, and Windows host
events including sleep and updates. A performance optimisation that adds a
failure mode is a net loss and should be rejected on those grounds.

---

## 9. Explicit refusal beats silent fallback

**The claim.** When the system cannot do something safely, it must stop and say
so, not approximate.

**What it forces.** Unmapped product and environment combinations are refused.
Preflight failures block startup rather than warning and continuing. Risk ceiling
breaches halt trading. Missing capability is reported to the operator, never
worked around silently.

Silent fallback is attractive because it keeps the system running. In a system
that moves money, continuing to run while being subtly wrong is the worse
outcome — and it is worse precisely because nobody notices.

---

## 10. Rules are enforced, not merely written

**The claim.** A policy that only exists in prose erodes, because nothing fails
when it is violated.

**What it forces.** Policies are encoded executably wherever possible. Project
identity, branch policy and phase count live in `src/globin/project_contract.py`
under test. The zero-budget rule is enforced by a test asserting the runtime
dependency list is empty. Documentation presence, structure and branch-policy
consistency are enforced by
`tests/contract/test_documentation_contract.py`. The roadmap document is checked against
the code skeleton rather than snapshotted.

This is why Phase 1 is a test-heavy phase that ships almost no behaviour: it
builds the mechanism that keeps the following 319 phases honest.
