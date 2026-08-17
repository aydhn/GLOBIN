# Telemetry Policy

What GLOBIN measures about itself, what a measurement may be labelled with, and
what may never become a label.

[`LOGGING_POLICY.md`](LOGGING_POLICY.md) owns records of *what happened*.
`engineering/RUNTIME_HEALTH.md` owns *is it well now*. This owns *what has it done
over time*, and the three are deliberately separate — collapsing any pair produces
the thing everybody regrets, which is a log message used as a metric label.

```bash
.venv\Scripts\globin.exe diagnostics telemetry
```

```bash
.venv\Scripts\globin.exe diagnostics telemetry --json
```

That command records nothing, starts nothing and binds nothing. Under `--json`
standard output carries the document and nothing else.

---

## The register

Every metric GLOBIN declares. The table is compared against `metrics()` in both
directions by `tests/contract/test_telemetry_policy_contract.py`, so a family added
to one and not the other fails.

| Metric | Kind | Unit | Attributes |
|---|---|---|---|
| `globin.telemetry.observations.total` | counter | count | `component`, `result` |
| `globin.telemetry.dropped.total` | counter | count | `reason` |
| `globin.telemetry.series.active` | gauge | count | — |
| `globin.telemetry.snapshot.nanoseconds` | histogram | seconds | — |
| `globin.diagnostics.http.requests.total` | counter | count | `route`, `status_class` |
| `globin.diagnostics.http.request.nanoseconds` | histogram | seconds | `route` |
| `globin.diagnostics.http.inflight` | gauge | count | — |
| `globin.diagnostics.http.rejected.total` | counter | count | `reason` |
| `globin.diagnostics.http.response.bytes.total` | counter | bytes | `route` |

**Every family names a capability GLOBIN has.** A descriptor named after one it does
not would be a claim that somebody is working on it — `REPOSITORY_LAYOUT.md`'s rule
about directories, applied to a register. Phase 026 declared the first four, about
telemetry itself; Phase 027 added five, about the diagnostics surface it built.
Market data, orders and strategies get theirs from the phases that build them.

**The five diagnostics families are the first whose dimensions a remote party could
try to choose, and every budget is arithmetic.** `route` is a six-member enum whose
sixth member is `unknown`, so ten thousand invented paths produce one series;
`status_class` is three; `reason` is six. Each family's budget is the exact product of
its own domains — 18, 6, 1, 6 and 6 — so a family cannot produce a series its
declaration did not predict, and adding a route changes both numbers in one edit.

Absent by construction, never by filtering: the raw path, the query string, the peer
address and port, any correlation, trace or request identifier, exception text, and
every header value. None of those is redacted out of a label — none can reach one.

---

## A name is declared, never generated

Lowercase, dot-separated, beginning `globin.`, three to six segments, each segment
starting with a letter. A counter ends in `total` and nothing else may; a metric
denominated in anything but `count` carries its unit's suffix.

**A name built from a value is the failure this prevents.** `f"globin.orders.{id}"`
is not a metric name, it is a series explosion with a metric name's syntax. Three
defences, in increasing strength: the recorder resolves every name against
`metrics()` before recording, so a generated name is unrecordable even if it is
constructible; `descriptor_for` raises `InternalError` on an unregistered name; and
an architecture test refuses a `MetricName` built from anything but a string
literal.

---

## Units are base units, stored as integers

| Unit | Stored as | Exporter spelling |
|---|---|---|
| `count` | a count | `1` |
| `bytes` | bytes | `By` |
| `seconds` | **nanoseconds** | `s` |
| `ratio` | **parts per million** | `1` |

`JsonCodec` refuses a `float` at any depth of a persisted document, so a value that
were floating point could not be published at all. Nanoseconds cost nothing:
`MonotonicReading.since` already returns integer nanoseconds, so an observation is
stored exactly as it was measured.

**The ceiling is `2**53 - 1`, and the reason is not Python's.** GLOBIN reads an
integer back exactly at any width. Every JSON consumer that is not Python holds
numbers as IEEE-754 doubles and silently drops low bits past that point — the same
corruption the float ban exists to prevent, arriving through the integer door.

**Prefer two counters to a ratio.** A ratio GLOBIN computes is a derived quantity,
and a derived quantity stored as fixed point is a rounding somebody owns for ever.
`ratio` exists for a quantity a *source* reports as a fraction.

---

## What may be a label

An attribute key must declare a **bounded set of permitted values**. That is not a
guideline: `AttributeDomain` refuses a key without one, and `MetricDescriptor`
refuses a descriptor whose product of domains exceeds its own cardinality budget.
The maximum number of series a family can produce is therefore arithmetic available
when the descriptor is written.

Good keys, and the values GLOBIN uses today:

| Key | Permitted values |
|---|---|
| `component` | `health`, `lifecycle`, `telemetry`, `watchdog` |
| `result` | `ok`, `error` |
| `reason` | `malformed`, `over_budget`, `refused` |

---

## What may never be a label

Two separate questions, two separate lists, and a contract test proves them
disjoint — because they are genuinely different questions and one list would answer
neither well.

**Would the value be a secret?** `is_sensitive` from `domain/observability.py`,
reused rather than restated: `api_key`, `apikey`, `authorization`, `cookie`,
`credential`, `passphrase`, `password`, `private_key`, `secret`, `session_id`,
`signature`, `token`.

**Would the value be unbounded?** A second list, and two shape rules that catch
every spelling rather than enumerating them:

- fragments — `address`, `email`, `hostname`, `identifier`, `message`, `order`,
  `path`, `symbol`, `thread`, `timestamp`, `trace`, `url`, `user`, `uuid`
- a key equal to `id` or ending `_id` — every identifier suffix at once
- a key ending `_at`, `_ms`, `_ns` or `_time` — every spelling of an instant

**A credential-shaped attribute is REFUSED, not redacted**, and that departs from
what `LogEvent` does on purpose. A log field is a leaf, so substituting it loses one
datum. An attribute is a *dimension*, so substituting it merges two series under a
name that means nothing — a real series with a fake identity.

**Screening returns codes, never the value.** The offending token is arbitrary
caller data that could be a credential, so nothing supplied ever reaches a return
value, a log record or a snapshot.

---

## Adding a metric

1. Add a `MetricDescriptor` to `metrics()` in `domain/metrics.py`, with a bounded
   `AttributeDomain` for every key it carries.
2. Add a row to the register above. The contract test compares the two.
3. Add a row to `otel_mapping()` and `prometheus_mapping()` — both are derived from
   the registry, so this is automatic, but the **collision test** is not: two
   families whose names differ only where Prometheus flattens them will fail it.
4. Record from a call site through `MetricRecorder`, never by touching the store.

**Do not add a metric for a capability that does not exist yet.** The register is a
claim about what GLOBIN measures, and a claim about what it is about to measure
belongs in the roadmap.

---

## What this does not cover

| Question | Phase |
|---|---|
| Collecting metrics from real trading subsystems | 280 |
| Retention, aggregation across runs, and long-term storage | 280 |
| Dashboards, alert rules and escalation | 315 |
| Instrumenting a Binance REST, WebSocket or FIX transport | 045 onwards |
| Which product and environment pairs exist | 036 |
