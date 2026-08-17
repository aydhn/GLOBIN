# Diagnostics Endpoint

How a running GLOBIN answers questions about itself over HTTP, what it will never
answer, and why the answer is reachable only from the machine it is running on.

Delivered by Phase 027 as its eleventh scope amendment. The decisions are in
[ADR-0072](../adr/0072-the-diagnostics-surface-is-loopback-only-read-only-and-bounded-by-construction.md);
the amendment itself, and the roadmap refusal it was taken against, are in
[ADR-0070](../adr/0070-phase-027-widens-to-deliver-the-loopback-diagnostics-surface.md).

---

## What this is for

Phases 024 to 026 gave GLOBIN a health snapshot, a watchdog and a telemetry registry.
Every one of them was reachable only by running a command, and two kinds of consumer
cannot run commands: a process supervisor that needs to poll liveness every second, and
a Prometheus scraper that speaks HTTP and nothing else.

This surface exists for exactly those two consumers. It is **off by default**.

## What this is not

It is **not** a remote administration API, an admin panel, a control plane, a
general-purpose web server or an internet-facing service. It has no way to change a
setting, restart a process, request a shutdown, download a support bundle, serve a file,
or accept a body. Every route is read-only, and the only methods it serves are `GET`
and `HEAD`.

**Do not widen the bind address.** There is no supported configuration in which this
surface is reachable from another machine, and the setting that names the address cannot
hold one — `LoopbackAddress` refuses anything `ipaddress` does not call loopback, so a
wildcard, a LAN address and a hostname are all rejected before a socket exists. If you
need observability from elsewhere, see [Remote observability](#remote-observability).

---

## Turning it on

Every setting is in the `diagnostics_http` section; the full register with defaults and
ranges is in [`../CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md).

```toml
[diagnostics_http]
enabled = true
```

Or, for one run, through the environment:

```bash
GLOBIN_DIAGNOSTICS_HTTP_ENABLED=true
```

With `enabled = false` — the default — **no server, socket, queue or worker thread is
constructed**. "GLOBIN is listening on nothing" is a property of the object graph rather
than of a branch, which is the same posture `telemetry.export_enabled` takes.

Ask what the surface would do without starting it:

```bash
.venv\Scripts\globin.exe diagnostics endpoint --json
```

That command binds nothing. It builds the policy — the object a server would be
constructed from — so it answers "would this start" without anything starting, and exits
`14` when the configuration is unusable. `bootstrap check` refuses the same
configuration with the same code.

---

## Routes

| Route | Answers | Switch |
|---|---|---|
| `GET`/`HEAD` `/health/live` | Whether the process is running and has not begun to stop | `health_enabled` |
| `GET`/`HEAD` `/health/ready` | Whether it is ready to do work, and why not if it is not | `health_enabled` |
| `GET`/`HEAD` `/health/runtime` | The Phase 024 health snapshot, redacted | `health_enabled` |
| `GET`/`HEAD` `/metrics` | The Phase 026 registry, as a scrape | `metrics_enabled` |
| `GET`/`HEAD` `/diagnostics/snapshot` | The health verdict *and* what telemetry measured | `diagnostics_snapshot_enabled`, off by default |

Anything else is `404`, including `/`, a static filename, and any attempt to climb out
of the tree. That is not a defence: a request target is looked up in a table of five
exact strings, so there is nowhere for a traversal to go. A query component is
discarded rather than parsed, so a cache-busting parameter is harmless and means
nothing.

A route whose switch is off also answers `404`, not `403`. Which diagnostics you chose
to withhold is not a caller's business.

### Liveness is not readiness

The distinction is the whole reason there are two routes, and conflating them is the
most common way a supervisor makes an incident worse.

**Liveness** answers *should this process be restarted*. It reads the shutdown signal
and **nothing else** — not the filesystem, not `psutil`, not a lock, not a health check.
A full disk does not make a process worth restarting, and a liveness endpoint that
failed because of one would turn a disk problem into a restart loop. It cannot reach a
health probe, so that independence is structural rather than remembered.

**Readiness** answers *should work be sent here*. It reports a bounded reason —
`ready`, `starting`, `stopping`, `configuration_invalid`, `dependency_unready`,
`unknown` — never a sentence, because a free-text reason is how an exception message
reaches a client. A stop request outranks a recorded `ready`, so whatever is sending
work learns to stop *before* the process stops accepting.

`200` means ready. `503` with a reason means not ready, and it is a **successful**
answer: the surface did its job. GLOBIN records it as such, so a starting process does
not appear broken on a dashboard.

### Runtime health

`/health/runtime` is a projection of the Phase 024 snapshot, built by the same
allowlist serializer the support bundle uses. There is no second health engine.

It answers `200` whatever the health *state* is, and the state is in the payload. A
transport that failed because a check warned would make "can I ask" and "is it well"
the same question; they are not, and `/health/ready` is where the second one belongs.
The document keeps its own schema, `globin.health.snapshot`, rather than being
relabelled — so a consumer knows what to parse it as.

The snapshot is **measured at most once a second** and reused in between. This surface
is reachable by anything on the machine that can open a socket, so without a floor the
polling rate would decide how much work GLOBIN does.

---

## Scraping

Point a scraper at it:

```yaml
scrape_configs:
  - job_name: globin
    static_configs:
      - targets: ['127.0.0.1:9464']
```

Port `9464` is the default, inherited from the scrape listener Phase 026 declared.

### Supported exposition formats

| Format | Content type |
|---|---|
| Prometheus text 0.0.4 | `text/plain; version=0.0.4; charset=utf-8` |
| OpenMetrics 1.0 | `application/openmetrics-text; version=1.0.0; charset=utf-8` |

Both are encoded by GLOBIN itself, so `/metrics` works on a host where
`prometheus_client` is not installed.

Selection follows the scrape protocol's rule — the highest-weighted offered protocol
that GLOBIN produces — with ties broken by the order the client wrote them. **There is
no `406`.** The specification's answer when nothing offered is supported is to fall back
to Prometheus text 0.0.4, so a malformed, hostile or absent `Accept` header and an
explicit request for 0.0.4 all reach the same format. A version GLOBIN does not produce
is a **non-match**, not a near-match: `text/plain; version=1.0.0` is
PrometheusText1.0.0, and answering it with 0.0.4 bytes would be a lie told in a header.

The `escaping=` parameter is read past and ignored; it belongs to formats GLOBIN does
not claim.

**No `# UNIT` line is emitted.** The specification's unit rule is conditional, and
GLOBIN's durations are integer nanoseconds by ADR-0068 — a `# UNIT` of `s` beside a
family named `..._nanoseconds` would be a false claim about its own numbers.

### It does not depend on an exporter

`/metrics` renders from the local registry. No remote collector is contacted on the
request path, so a collector that is down, slow or misconfigured cannot affect a scrape
and cannot appear in a request's critical path. Whether telemetry is *exported* is
`telemetry.export_enabled`'s question and is unrelated.

---

## What every response guarantees

- An explicit `Content-Type` and an explicit `Content-Length`, on `HEAD` as well as
  `GET`.
- `Cache-Control: no-store` and `Pragma: no-cache`. Not `no-cache` alone, which permits
  storing the response.
- `X-Content-Type-Options: nosniff`.
- **No `Server` header**, and no Python or library version anywhere. Responses are
  written through `send_response_only`, which does not add one.
- No HTML. An error is a small plain-text body with a constant message.
- No request header, target or query is ever echoed into a response, so there is no
  source for a split header.

An unsupported method is `405` with `Allow: GET, HEAD`. A request carrying or announcing
a body is `400` — a body this surface never reads would be left in the socket for
whatever came next.

### Redaction

No response, log record or metric label carries an API key, a secret, a passphrase, a
private key, an authorisation header, a cookie, a token, a resolved `SecretRef`, the
environment, a command line, a stack trace or a filesystem path outside what the health
snapshot's own redaction already permits.

**The limit is worth stating.** Redaction is by field *name*, so a credential inside an
exception *message* would be written. This surface's answer is not to redact those but
to never send them: a failed request is answered with a constant body that is identical
for every cause, and only the exception's **type** is recorded.

---

## Limits

| Setting | Default | What it bounds |
|---|---|---|
| `max_concurrent_requests` | 4 | Requests in flight, which is also the worker-thread count |
| `max_response_bytes` | 1 MiB | The largest body sent |
| `request_timeout_seconds` | 5 | How long one request may occupy a worker |
| `shutdown_timeout_seconds` | 5 | How long in-flight requests get to finish |

There is **no thread per connection**. A fixed pool of non-daemon workers is created at
start and drains a bounded queue; when the queue is full the connection is answered
`503` on the accept loop and closed. So capacity exhaustion is a refusal rather than
thread growth, and the worker count *is* `max_concurrent_requests` — there is no second
limit to get wrong.

A response over its size bound is **refused, not truncated**. Half a JSON document is
not a smaller answer, and an OpenMetrics exposition missing its terminator is rejected
by every conforming parser, so truncating would produce data a consumer cannot tell
from corruption.

---

## Starting and stopping

The surface is registered with the Phase 022 lifecycle, so an orderly shutdown stops
accepting, drains what is in flight within `shutdown_timeout_seconds`, closes the
socket, and joins every worker. `start` and `stop` are both idempotent.

A worker still busy when the deadline passes is **recorded and left**. Joining it
without a bound would let one wedged request stop the process from ever exiting, which
is the failure Phase 025's watchdog exists to end.

Startup is fail-closed. An address that is not loopback, or a bound outside its range,
is refused when the configuration is bound — before a socket exists — and reported as
exit `14`. If the port cannot be bound, start-up fails rather than continuing with a
surface that will never answer.

---

## Troubleshooting

| Symptom | Cause | What to do |
|---|---|---|
| Connection refused | `enabled` is false, which is the default | Set `diagnostics_http.enabled` |
| Exit `14` at start-up | The address is not loopback, or a bound is out of range | Run `globin diagnostics endpoint`; it names every problem at once |
| `404` on a route you expected | That route's switch is off | `health_enabled`, `metrics_enabled`, `diagnostics_snapshot_enabled` |
| `404` on `/diagnostics/snapshot` | Off even when the surface is on | Set `diagnostics_snapshot_enabled` |
| `503` on `/health/ready`, forever | Nothing has marked the run ready | Expected before start-up completes; check `bootstrap check` |
| `503` with "at capacity" | Every worker is busy and the queue is full | Poll less often, or raise `max_concurrent_requests` |
| `500` "exceeded its configured size bound" | A document grew past `max_response_bytes` | Raise the bound; the refusal is deliberate |
| `405` | You used a method other than `GET` or `HEAD` | There is no state to change here |
| Empty `/metrics` | Nothing has been recorded yet | Expected on a process that has just started |

---

## Security boundary

The boundary is **loopback-only, read-only, and minimal surface**, in that order. It is
not authentication: this phase adds no token, no password and no TLS, because on a
loopback-only read-only surface those would be ceremony rather than defence — anything
able to reach the socket is already running on the machine as a user who could read the
process's memory.

What holds the boundary:

- The bind address is a **type** that refuses everything but loopback, so the setting
  cannot hold a reachable address.
- The peer address is checked again on accept, which should be unreachable and costs one
  comparison.
- Exactly **one module** in GLOBIN may reach a socket, and
  `tests/architecture/test_library_discipline.py` fails if a second one does — and fails
  if that module contains *any* address literal, loopback included.
- No wildcard address is spelled anywhere in `src/globin`.

### Why the standard library

`http.server`'s own documentation says it is *"not recommended for production. It only
implements basic security checks."* That warning is about serving files to untrusted
clients, and this serves no files: no static content, no directory logic, no CGI, no
routing framework, and a request target looked up in a five-entry table. What remains
is a request parser and a socket, which is the smallest correct thing for a read-only
surface only this machine can reach — and a web framework would have been a larger
dependency and a larger attack surface for the same five documents.

### Remote observability

<a id="remote-observability"></a>

If GLOBIN's metrics or health must be visible from another machine, **the answer is not
to widen this bind address**, and the type will not let you.

The supported shape is a separate component: an authenticated, TLS-capable collector or
gateway — a Prometheus server, an OpenTelemetry Collector, or a supervisor — that runs
on this machine, scrapes `127.0.0.1` locally, and forwards onward over a channel with
its own identity, transport security and access control. That component's deployment,
configuration and credentials are out of scope for Phase 027 and are named in
`ROADMAP.md` at Phase 280 (*Operational Metrics Collection*) and Phase 315 (*Live
Monitoring and Escalation*). Nothing in this phase installs, configures or manages one.

---

## Related documents

| Question | Document |
|---|---|
| Which settings exist, and what are their ranges? | [`../CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md) |
| What does the health snapshot contain? | [`RUNTIME_HEALTH.md`](RUNTIME_HEALTH.md) |
| What does telemetry declare, and what does it export? | [`RUNTIME_TELEMETRY.md`](RUNTIME_TELEMETRY.md), [`../TELEMETRY_POLICY.md`](../TELEMETRY_POLICY.md) |
| How does the process start and stop? | [`BOOTSTRAP.md`](BOOTSTRAP.md), [`RUNTIME_FILESYSTEM.md`](RUNTIME_FILESYSTEM.md) |
| Where may a secret live, and what is redacted? | [`../security/SECURITY_BASELINE.md`](../security/SECURITY_BASELINE.md) |
| What sources does this rest on? | [`../research/phase_027_sources.md`](../research/phase_027_sources.md) |
