# Runtime Telemetry

How a running GLOBIN measures itself, and what stops a measurement becoming a
liability.

[`RUNTIME_HEALTH.md`](RUNTIME_HEALTH.md) answers *how is it doing now*. This answers
the different question *what has it done over time*. A health check is an
instantaneous verdict that an operator reads once; a metric is a number that only
means anything aggregated, and the two are separate subsystems because collapsing
them produces a health snapshot with unbounded history or a metric that reports a
verdict.

```bash
.venv\Scripts\globin.exe diagnostics telemetry
```

```bash
.venv\Scripts\globin.exe diagnostics telemetry --json
```

**That command records nothing, starts nothing and binds nothing.** It reports what
the registry declares and what the configuration would do, and exits `OK` whatever
state export is in.

---

## Nothing leaves this machine unless somebody says so

`telemetry.export_enabled` is **off by default**, and "off" is an object graph
rather than a flag: with it off, no exporter, queue, pump or thread is constructed
at all. "GLOBIN opens no socket" is therefore structural rather than a branch
somebody could get wrong.

`telemetry.listener_enabled` is separately off. When it is on, the Prometheus
scrape endpoint binds **`127.0.0.1` as a literal**, and there is deliberately no
address setting. `prometheus_client.start_http_server` defaults its address to
`0.0.0.0` — every interface, not this machine — which is exactly the class of
mitigation this repository refuses to leave to somebody remembering.
`tests/architecture/test_library_discipline.py` asserts the literal is there, the
wildcard is not, and no second route to a listener exists.

---

## Cardinality is arithmetic, not a hope

Every attribute key must declare a bounded set of permitted values. Because the
domains are bounded, the most series a family can produce is the product of their
sizes — a number available when the descriptor is written. `MetricDescriptor`
refuses a descriptor whose product exceeds its own budget, so a family that could
explode **cannot be constructed**.

The runtime budget check still exists and is provably unreachable for a correct
registry. A property test asserts it never fires for anything `metrics()` returns;
a unit test reaches it only by pre-filling a family by hand. A check whose failing
case is never exercised is indistinguishable from one that cannot fire.

---

## A refused observation costs a counter and nothing else

A telemetry call sits inside the code it is measuring, so nothing in the recording
path raises. Every refusal is dropped and counted, by the rule that refused it:
`refused` (the attributes did not satisfy the family), `over_budget` (a new series
would have passed the limit), `malformed` (the value itself).

**A rejected series key is never stored, never logged and never published.** The
whole point of a budget is that an unbounded value set cannot grow anything, and a
drop path that recorded what it rejected would grow a table instead of a series.

**Drop logging is itself bounded.** The first drop per `(metric, reason)` is
announced and the rest are counted, because a record per drop turns a cardinality
explosion into a log explosion — and the rotation policy would then discard the
record that mattered.

---

## Determinism, claimed narrowly

Two snapshots taken at different moments differ, because a counter grows and a
duration moves. Promising otherwise would be a guarantee nobody could keep.

What **is** guaranteed for the same logical work, and what a digest may be taken
over, is `TelemetrySnapshot.shape()`: the family list and its order, each family's
unit, kind and bucket boundaries, and each family's series keys. `document()` holds
the measurements. This is the split `GPU_BENEFIT.md` already describes for the one
manifest that is not byte-stable.

---

## Spans, and the one context variable

A span is the third shape. It says *this unit of work took this long and happened
inside that one*, and the parent link is the only part that cannot be a parameter:
it is a statement about the dynamic call structure, which is what a span tree
measures.

[ADR-0026](../adr/0026-correlation-is-bound-explicitly-not-ambiently.md) refuses
`contextvars` for the **correlation id**, and that stays refused. The span scope
holds a `SpanContext` and nothing else, is an instance attribute rather than a
module global, and never constructs or reads a `Logger`.
`tests/architecture/test_context_discipline.py` asserts both.

**Async propagation is tested without an event loop**, and that is a finding rather
than a shortcut: on Windows the default loop builds its self-pipe from
`socket.socketpair()`, whose fallback calls `connect()`, which the offline test
guard fails. The mechanism a task actually uses is `contextvars.copy_context()`, so
that is what the tests exercise — the identical call, with no loop and no socket.

**A new thread inherits no context.** A worker that should nest under its caller is
handed the `SpanContext` as a value and opens with `parent=`, which is ADR-0026's
own prescription rather than a new mechanism.

**A fault is a type name, never a message.** An exception message is arbitrary text
that may carry a path, a credential or a whole request body, and a span travels.

---

## Delivery is bounded, and retirement is permanent

The queue is bounded and drops the **oldest** when full: telemetry's value increases
with recency, and during an incident the observation most worth having is the one
that just happened.

The state machine has one edge into `STOPPED` and **none out of it**, so "GLOBIN
never hammers a dead endpoint" is a property of the graph rather than of a counter.
A permanent failure retires the exporter for the life of the process; repeated
temporary failures do the same after a declared count.

A batch is consumed **only** on `DELIVERED`. Anything else means the exporter still
has nothing, and the documents are restored — which is what stops a transient
failure losing data silently.

Transitions produce records; ticks do not. A pump logging every failed attempt at a
five-second interval writes seventeen thousand records a day.

---

## Configuration

| Setting | Default |
|---|---|
| `telemetry.enabled` | `true` |
| `telemetry.export_enabled` | `false` |
| `telemetry.listener_enabled` | `false` |
| `telemetry.listener_port` | `9464` |
| `telemetry.queue_capacity` | `256` |
| `telemetry.batch_size` | `32` |
| `telemetry.flush_millis` | `5000` |

There is no exporter setting. `runtime/composition.py`'s own rule is that these
functions build rather than choose, and a configuration value that selected a
provider would be a value that could open a socket.

---

## Limitations

**Nothing outside telemetry is instrumented yet.** The registry declares four
families and they describe telemetry itself. That is deliberate: a descriptor named
after a capability GLOBIN does not have is a claim somebody is working on it.

**Optional attributes are impossible.** Every declared key must be supplied, or one
family would have two series shapes and aggregation would break silently. The
sanctioned answers are a bounded domain with an explicit `"none"` member, or two
families.

**`offer` cannot be time-bounded from the caller.** CPython gives no way to
interrupt a blocked call from another thread, so the attempt timeout is a contract
on the implementer. The exporters GLOBIN ships cannot block indefinitely; a
third-party one could, and pretending otherwise with a timer would be building the
supervisor Phase 263 owns.

**Neither provider library is in `stack-contract.toml`.** That contract feeds the
forbidden-import tripwire, so listing an adopted library would forbid the adapter
that imports it. The gap and its fix are recorded in
[ADR-0068](../adr/0068-telemetry-is-provider-neutral-and-cardinality-is-bounded-by-construction.md).

---

## What this does not do

| Question | Phase |
|---|---|
| Collect metrics from real trading subsystems | 280 |
| Retain, aggregate across runs, or store long-term | 280 |
| Dashboards, alert rules and escalation | 315 |
| Instrument a Binance transport | 045 onwards |

---

## Related documents

- [`../TELEMETRY_POLICY.md`](../TELEMETRY_POLICY.md) — the register and the
  attribute rules.
- [`RUNTIME_HEALTH.md`](RUNTIME_HEALTH.md) — the neighbouring subsystem.
- [`RUNTIME_WATCHDOG.md`](RUNTIME_WATCHDOG.md) — whose thread and tick shape the
  pump borrows.
- [ADR-0068](../adr/0068-telemetry-is-provider-neutral-and-cardinality-is-bounded-by-construction.md)
  — the contract.
