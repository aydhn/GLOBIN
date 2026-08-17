# ADR-0072 — The diagnostics surface is loopback-only by type, read-only, and bounded by construction

## Status

Accepted — Phase 027.

**Date:** 2026-08-17

## Context

Phases 024 to 026 gave GLOBIN a health snapshot, a watchdog and a telemetry registry,
all reachable only by running a command. A supervisor cannot run a command every
second, and a Prometheus scraper cannot run one at all.

Phase 026 anticipated this and got half of it wrong in an instructive way. It declared
`telemetry.listener_enabled` and `telemetry.listener_port`, and wrote
`start_loopback_listener` — which served a `CollectorRegistry` that GLOBIN never
populated, so it would have answered a scrape with an empty exposition. It had no
production caller. The settings were dead and the function was dead.

Phase 026 also decided, correctly and for the right reason, that there would be **no
bind address setting at all**: `prometheus_client.start_http_server` defaults to every
interface, and a configurable address is one typo from publishing a process's internals.

## Decision

**One socket, one module, and the address is a type rather than a literal.**

`LoopbackAddress` refuses anything `ipaddress` does not call loopback. So
`diagnostics_http.bind_host` **cannot hold** a wildcard, a LAN address or a hostname —
not "is validated on the way in", but has no state in which a non-loopback address
exists inside GLOBIN. The refusal covers spellings a denylist would not have enumerated:
four zeroes, a bare zero, hexadecimal, a bare pair of colons, an IPv4-mapped form,
loopback as a decimal integer. A hostname is refused rather than resolved, because
resolution is I/O and a name that resolves to loopback today may not tomorrow.

**Phase 026's listener is retired, and `start_http_server` joins the forbidden list.**
`tests/architecture/test_library_discipline.py` now names one module that may reach a
socket, forbids every library route including the one that used to be permitted, and
asserts the binding module contains **no address literal of any kind** — an address it
cannot spell is one it cannot bind.

**The standard library, and a bounded pool rather than a thread per connection.**
`ThreadingHTTPServer` is unbounded by construction and marks its threads daemons.
`process_request` — the same documented hook that mixin overrides — hands a connection
to a bounded queue drained by a fixed pool of non-daemon workers. The worker count *is*
`max_concurrent_requests`; a full queue is a deterministic 503 written on the accept
loop.

**`GET` and `HEAD` only, and `send_error` is overridden.** Defining two handlers leaves
the base class to answer every other verb with a **generic HTML page** carrying the
requested method, no cache directive and no sniffing refusal — the same path taken by a
malformed request line. One override closes all of it; enumerating verbs never could,
because the set is unbounded.

**Everything decidable without a socket is decided without one.** Routes, formats,
limits and addresses are values; request-to-response is a pure function in the
application layer. The adapter is left with accept, admit, parse, write.

**Negotiation is total, and there is no 406.** The scrape protocol's own rule is that a
target supporting none of the offered protocols *"MUST use PrometheusText0.0.4 as a
last resort"*.

**No `# UNIT` line.** The specification's unit rule is conditional, and GLOBIN's
durations are integer nanoseconds by ADR-0068 — a `# UNIT` of `s` beside a family named
`..._nanoseconds` would be a false claim about its own numbers.

## Consequences

**This supersedes the "no address setting" half of ADR-0068, and replaces a literal
with something stronger.** That decision was right about the danger and reached for the
wrong instrument: a literal keeps the address safe while making `::1` unreachable, and
it puts the guarantee in a constant somebody can edit. A validated value type keeps IPv6
available and moves the guarantee into the type system. Everything else ADR-0068 decided
— provider neutrality, integer values, bounded cardinality, export off by default —
stands unchanged.

**Cardinality stays arithmetic on a surface a remote party can reach.** Five families,
each with a budget equal to the exact product of its own attribute domains: 18, 6, 1, 6,
6. The dimensions a caller could otherwise choose are absent by construction — the route
*enum* is recorded, whose unrecognised member is the single value `unknown`, so ten
thousand invented paths produce one series.

**A disabled route answers 404, not 403.** Which diagnostics an operator withheld is not
a caller's business.

**A truthful 503 is a success.** Readiness answering "starting" is the surface doing its
job; recording it as an error would make a healthy process look broken.

**The health projection is cached for one second.** This surface is reachable by
anything on the machine that can open a socket, so without a floor the polling rate
would decide how much work GLOBIN does. A bound on cost, not a performance tweak.

**A stated limitation: liveness reports the process, not the surface.**
`RuntimeHealthSnapshot` gained no endpoint summary, so `/health/runtime` describes the
runtime rather than the mechanism reporting on it. The surface's own state is reported by
`globin diagnostics endpoint`, and an unusable configuration is refused by `bootstrap
check` with exit 14. Widening the health model to describe its own transport was judged
the wrong direction.

**A second stated limitation: `prometheus_client` is now held for almost nothing.**
GLOBIN encodes both formats itself, so the library's only remaining role is that
constructing a `CollectorRegistry` proves it is importable — which is the state
`diagnostics telemetry` reports. That is thin, and it is said plainly in the module
rather than dressed up.

## Alternatives Considered

**A web framework.** FastAPI, Flask or aiohttp would each be a runtime dependency, a
routing engine, a middleware stack and a template layer, for five documents on a
loopback socket. Refused on attack surface as much as on dependency policy.

**`prometheus_client`'s own WSGI app or `start_http_server`.** Serves `/metrics` and
cannot serve health; defaults its address to every interface; and offers none of the
bounded concurrency, size limits or header hardening this surface is required to have.

**Keep Phase 026's listener beside the new one.** Backward compatible, and two routes to
a socket — one working, one dormant and serving an empty exposition — is the second
independent source of truth this repository refuses. The owner was shown the trade and
chose retirement.

**No `bind_host` setting, keeping a literal and a boolean for IPv6.** Preserves ADR-0068
exactly and puts the guarantee in a constant rather than a type. The value type is
stronger and admits `::1` without a second switch.

**Answer 406 when no offered format is supported.** Refused: the specification declines
to use that status here, and inventing one would make GLOBIN the only target in a scrape
fleet that does.

## Risks and Trade-offs

**`http.server` is documented as "not recommended for production".** That warning is
about serving files to untrusted clients: this serves no files, has no directory logic
and no CGI, and is reachable only from this machine. The trade is stated rather than
waved away, and the mitigation is that the module is small enough to read.

**A bounded pool refuses under load where an unbounded one would degrade.** Deliberate.
A refusal is a number an operator can see; unbounded thread growth is a process that
stops answering for reasons nobody can attribute.

**`HTTP/1.0` costs a scraper one handshake per scrape.** Keep-alive would let an idle
connection hold one of four pool slots.

**A worker still busy at the shutdown deadline is left, not joined.** Joining without a
bound would let one wedged request prevent the process from ever exiting — the failure
Phase 025's watchdog exists to end. The straggler is recorded.

**Remote observability is not solved and must not be reached for here.** Widening the
bind address is the wrong answer and the type now forbids it. A future phase that needs
it builds an authenticated, TLS-capable collector or gateway that scrapes this surface
locally; [`../engineering/DIAGNOSTICS_ENDPOINT.md`](../engineering/DIAGNOSTICS_ENDPOINT.md)
says so where an operator will look.

## References

- [`../engineering/DIAGNOSTICS_ENDPOINT.md`](../engineering/DIAGNOSTICS_ENDPOINT.md) —
  the operator-facing contract.
- [`../research/phase_027_sources.md`](../research/phase_027_sources.md) — the scrape
  negotiation, OpenMetrics and `http.server` sources this rests on.
- [ADR-0068](0068-telemetry-is-provider-neutral-and-cardinality-is-bounded-by-construction.md)
  — whose address decision this replaces and whose cardinality argument it keeps.
- [ADR-0061](0061-phase-024-widens-to-deliver-runtime-health-and-support-bundles.md) —
  the health snapshot this projects.
- [ADR-0059](0059-the-mutable-runtime-tree-is-user-local-and-one-coordinator-is-proved-by-a-lock.md)
  — the lifecycle this stops within.
- [ADR-0070](0070-phase-027-widens-to-deliver-the-loopback-diagnostics-surface.md) — the
  amendment that carried this phase.

## Supersedes

Nothing.

<!--
This section is machine-parsed: `tests/contract/test_documentation_contract.py` reads
any ADR number appearing here as a supersession claim and requires the named record to
carry a matching `Superseded By`. The relationship to Phase 026's address decision is
therefore stated in `## Consequences` and `## References`, where prose is prose — this
record replaces one *mechanism* that record chose, and displaces none of its decisions,
which is not a supersession.
-->

## Superseded By

Nothing.
