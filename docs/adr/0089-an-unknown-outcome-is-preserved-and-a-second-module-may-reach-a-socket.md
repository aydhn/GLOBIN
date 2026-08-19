# ADR-0089 — An unknown outcome is preserved, and a second module may reach a socket

## Status

Accepted — Phase 034. **Date:** 2026-08-19

## Context

Phase 034 gave GLOBIN a REST transport. Two decisions inside it are load-bearing
enough to record separately from the scope amendment
([ADR-0088](0088-phase-034-widens-to-deliver-the-rest-transport-substrate.md)),
because a later phase could plausibly undo either without realising what it cost.

### The outcome that is neither success nor failure

Binance documents, of a 5XX response: *"It is important to **NOT** treat this as a
failure operation; the execution status is **UNKNOWN**."* Of error `-1007`: *"Send
status unknown; execution status unknown"*, adding that it *"does not always mean
that the request failed in the Matching Engine."*

A transport that models two outcomes has nowhere to put that. Every state which is
not success becomes failure, every failure looks retryable, and the system places
the order twice.

The pressure to collapse it is real and comes from the language rather than from
carelessness. An exception *is* the idiomatic way to report a failed request, and
every caller writes `except TransportError` and treats the body as the
did-not-happen path. So the natural implementation destroys the distinction on the
way out.

### The property that ended

From Phase 001 to Phase 033, `src/globin` opened no outbound connection at all.
`tests/architecture/test_library_discipline.py` named exactly one module that could
reach a socket — the loopback diagnostics listener added by Phase 027 — and guarded
`socket`, `socketserver` and `http.server`.

Two things were found while extending it.

**The outbound routes were never guarded.** `http.client`, `urllib.request` and
`ssl` appeared in no rule. Any module in the package could have reached the
internet and nothing would have noticed. The property held because nobody had
written the code, not because anything prevented it.

**The matcher had never worked for a dotted name.** `_imports` compared
`name.split(".")[0]` against the guard, so `http.server` — in the guarded list
since Phase 026 — matched nothing at all. The rule passed its own guard-the-guard
test the whole time, because `socketserver` is a single segment and one satisfied
route was enough to prove the module reached *a* socket.

## Decision

### An unknown outcome is preserved, and never retried

`RequestOutcome` has five members: `SUCCESS_CONFIRMED`, `FAILURE_CONFIRMED`,
`UNKNOWN`, `NOT_SENT`, `REJECTED_BEFORE_SEND`. Nothing in this repository may map
`UNKNOWN` onto a failure.

**A transport returns its outcome; it does not raise one.**
`RestTransport.send()` returns a `RestExchange` for every network, protocol and
venue condition, and raises only for a fault in GLOBIN itself. That is what stops a
caller's `except` block from quietly converting the one state this phase exists to
preserve into the one thing it must never become.

**Classification takes the side effect as an input.** The same 503 is a confirmed
failure for a read and `UNKNOWN` for a write, because nothing is at stake in a
query. A read-only request can never return `UNKNOWN`.

**403, 418 and 429 are confirmed even for a write.** All three are refusals at the
edge before any matching engine. Recording them ambiguous would be unsafe rather
than cautious: nothing retries `UNKNOWN`, so an ordinary rate-limit rejection —
the one failure that is always retryable — would become permanently unretryable.

**Nothing retries, and no parameter would make it.** Phase 043 owns retry and
inherits the prohibition.

**The send state advances before the write, not after.** Once the socket is up,
GLOBIN cannot prove the bytes stayed in this process, so a failure while writing is
`SENT` and therefore `UNKNOWN` for a mutating request. Being wrong in this
direction costs a duplicate check; being wrong in the other costs a duplicate
order.

### Exactly two modules may touch a socket, one direction each

| Module | May | May not |
|---|---|---|
| `globin.adapters.diagnostics_http` | listen (`socketserver`, `http.server`) | reach outward |
| `globin.adapters.rest_transport` | reach outward (`http.client`, `urllib.request`, `ssl`) | listen |

`socket` is permitted in both and nowhere else — it cannot be assigned to one role,
because the listener binds one and the client connects one.

Both halves are asserted in both directions: a third module naming any route fails,
and either of the two losing its route fails as well. Neither may grow the other's
role — without that, naming a second socket-capable module would have widened the
rule twice over while the count still read two.

`_covers` compares dotted names exactly, so `http.client` and `http.server` are
distinguishable. The whole guard-the-guard set is parametrised, including every
dotted case that silently passed before.

**TLS verification has no off switch.** `secure_context()` takes no arguments, and
`tests/contract/test_rest_contract.py` proves no `CERT_NONE`, `CERT_OPTIONAL` or
`_create_unverified_context` appears as *code* anywhere in the package — read from
the AST rather than the text, because the first draft flagged the transport's own
docstring explaining the rule.

## Consequences

The outbound half of the socket rule is **stronger** than what it replaced, not
weaker. Before this phase three routes to the internet were unguarded and one
guarded route never matched; after it, every route is named and the matcher is
exact.

A future phase that wants a second outbound module must edit a named constant and
justify it, rather than adding an import nobody notices.

Phase 043 inherits a transport it cannot ask to retry. Phase 044 inherits an
`ExchangeFault` carrying the venue's code uninterpreted, and a five-member outcome
its classification must not flatten. Phase 038 inherits a canonical request whose
rendering is byte-stable and pinned by vectors.

`globin.errors.TransportError` and `ExchangeError` remain for a caller that has
read an exchange and decided to escalate. The transport raises neither.

## Alternatives Considered

**Raise `TransportError` for a network fault, as the taxonomy's docstrings
suggest.** Rejected on the reasoning above: the exception is the mechanism that
destroys `UNKNOWN`. The classes stay for callers above the transport, which is what
they were always for — the docstrings say *"Phases 033-048 introduce the callers"*,
not *"the transport raises them"*.

**A three-member outcome — success, failure, error.** Rejected. It is the shape
that places the order twice, and it is the common shape precisely because the
fourth and fifth states only matter on the day they matter.

**Treat every 5XX as retryable and let Phase 043 decide.** Rejected. It moves a
correctness decision into a phase that will be reasoning about backoff curves, and
it makes the safe default the one somebody has to remember.

**Mark 403, 418 and 429 ambiguous "to be safe".** Rejected after working the
consequence through: caution in that direction removes the only always-safe retry
from the one phase that needs it.

**Keep one socket-capable module and put the probes in `tools/`.** Considered
seriously — it preserves the stated property intact, and `venue refresh` already
reaches the network from there. Rejected by the operator, who chose real
`globin rest ping` and `rest server-time` verbs. The cost is recorded here; the
mitigation is the two-role rule.

**Allow a `verify: bool` on the connection factory for testing.** Rejected. That is
the whole security posture reduced to a keyword somebody could default wrongly. The
seam is the entire factory, visible in a constructor call, and
`ResolvedEndpoint` refuses any URL that is not HTTPS, so no factory can be pointed
at a plaintext venue endpoint.

## Risks and Trade-offs

**`UNKNOWN` is a state callers must handle, and some will not.** It cannot be made
impossible to ignore; what it can be is impossible to *lose*, which is why it is
returned rather than raised and why `RestExchange.at_risk` is a named property
rather than a comparison each caller writes.

**The two-module rule is a proxy, not a proof.** A module handed an open socket, or
reaching one through `importlib`, defeats it. It catches the realistic erosion —
somebody importing `http.client` in a second place because it was convenient — and
it is asserted in both directions so it cannot pass by nobody doing anything.

**The conservative `SENT` boundary over-reports uncertainty.** A request that
failed on the first byte of the write is reported as possibly-sent. That is
deliberate, and the cost is one extra query at Phase 043 rather than one extra
order.

**No CI machine exercises the outbound path.** The external tests are excluded from
every quality selection by design, so the claim *"this works against the real
venue"* rests on a deliberate local run, recorded in the phase report rather than
in a green badge.

## References

- [`docs/engineering/REST_TRANSPORT.md`](../engineering/REST_TRANSPORT.md) — the engineering record
- [`docs/research/phase_034_sources.md`](../research/phase_034_sources.md) — S-01 and S-05, the two sources this rests on
- [ADR-0072](0072-the-diagnostics-surface-is-loopback-only-read-only-and-bounded-by-construction.md) — the listener half of the socket rule
- [ADR-0085](0085-a-plan-is-derived-from-a-report-and-one-module-may-start-a-process.md) — the same shape for `subprocess`
- [ADR-0022](0022-error-taxonomy-rooted-in-one-type.md) — where `TransportError` and `ExchangeError` came from

## Supersedes

None.

## Superseded By

None.
