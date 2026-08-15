# Logging Policy

How GLOBIN records what it did, what each severity means, and why a credential
cannot reach an output stream.

This document owns logging policy. The configuration it describes lives in
[`src/globin/domain/observability.py`](../src/globin/domain/observability.py) and
[`src/globin/adapters/observability.py`](../src/globin/adapters/observability.py),
and `tests/contract/test_observability_contract.py` compares the two so that a
rule changed in one place cannot stay unchanged here.

---

## Events, not sentences

A call site names an event and attaches fields. It never interpolates a value
into a message.

```python
logger.info("order.submitted", symbol="BTCUSDT", quantity=0.5)
```

Not `logger.info(f"Submitted 0.5 BTCUSDT")`. The difference is not stylistic.
Structured fields are what make a log searchable by symbol rather than by
substring, and — more importantly here — they are what make redaction possible
at all. If a value can only arrive as a field, then inspecting field *names* is
enough to stop a secret being printed. The moment a value is interpolated into
a message, no rule about names can catch it.

Event names are lowercase dotted identifiers: `order.submitted`,
`architecture.review.completed`. They are constants, so that the set of things
GLOBIN can report is enumerable rather than discovered by reading log output.

---

## Record shape

One JSON object per line. The four envelope keys come first, in this order,
followed by `fields`.

### Envelope keys

- `timestamp`
- `severity`
- `event`
- `correlation_id`

Structured detail is nested under `fields` rather than merged into the envelope,
so that a field named `event` cannot displace the event name. `fields` is
present even when empty, so nothing reading the output needs a conditional.

Non-ASCII characters are escaped. That costs readability for Turkish or symbol
text and buys the guarantee that a record can be written whatever encoding the
stream happens to have — GLOBIN's host is Windows, where a console stream is
frequently not UTF-8, and a logger that raises on a symbol name fails exactly
when something interesting is happening.

Timestamps are timezone-aware and UTC. Since Phase 009 the value comes from a
[`Clock`](../src/globin/ports/clock.py) the sink is handed rather than from a call
inside the sink, and it is read once per record. The general rule is
[`TIME_POLICY.md`](TIME_POLICY.md).

---

## Severity policy

| Level | Meaning | Reach for it when |
|---|---|---|
| `DEBUG` | Detail useful only while diagnosing something | You are tracing a decision and would not want the line in normal operation |
| `INFO` | Something happened that an operator would want to see | A unit of work started, finished, or produced a result worth recording |
| `WARNING` | Something unexpected, which GLOBIN handled and continued past | A retry succeeded, a value fell back to a default, a limit was approached |
| `ERROR` | Work did not complete | A request failed after its retries, a use case gave up |
| `CRITICAL` | GLOBIN cannot do its job at all | A configuration is unusable, an invariant that must hold has not |

Two rules that are easy to get wrong:

**A handled fault is a `WARNING`, not an `ERROR`.** Severity describes the
outcome of the work, not the drama of the code path. A retry that eventually
succeeded produced the right answer.

**`CRITICAL` is not "a very bad `ERROR`".** It means the process cannot
continue doing its job, which is a different claim from a piece of work having
failed. A system where routine failures are logged as `CRITICAL` cannot be
alerted on.

Severity itself carries no threshold. Deciding which records are worth keeping is
a sink's concern, and Phase 007 settled it there: `ThresholdLogSink` wraps another
sink and forwards a record only when its severity reaches a configured minimum.

The minimum is the `logging.min_severity` setting in
[`CONFIGURATION_POLICY.md`](CONFIGURATION_POLICY.md), and it defaults to the
lowest level, so nothing is discarded until an operator asks for it. Two sinks may
hold different thresholds over the same events — a file keeping everything beside
a console keeping only what went wrong — which is why the comparison lives in a
sink rather than in the logger. The reasoning is
[ADR-0029](adr/0029-a-severity-threshold-is-a-decorating-sink.md).

---

## Correlation

Every record carries a `correlation_id` tying it to the others produced by the
same piece of work. It is supplied, not discovered: a logger is constructed with
one, and `bind` returns a *new* logger rather than mutating the one it was
called on.

```python
run_logger = logger.bind(component="review")
```

GLOBIN deliberately does not use a context variable for this. An ambient
correlation id would let any code log with the right identifier without being
handed anything, which is convenient and is exactly the hidden global state
[`ENGINEERING_CONTRACT.md`](engineering/ENGINEERING_CONTRACT.md) invariant 5
forbids. It would also make a test's output depend on what an earlier test set,
which the process-state isolation established in Phase 005 exists to prevent.

Explicit binding costs an argument at each boundary. What it buys is a logger
whose output is a function of what you passed it.

---

## Redaction

A field whose **name** matches any fragment below has its **value** replaced
with `[redacted]` before the record exists. This happens during construction of
the record itself, not in the sink, so a sink written in a later phase cannot
leak a credential by forgetting to call something.
[`ENGINEERING_CONTRACT.md`](engineering/ENGINEERING_CONTRACT.md) invariant 24 is
absolute, and an absolute rule enforced by convention is not enforced.

Matching is a case-insensitive **substring** test. A field called
`binance_api_key` is exactly the one that must not be printed, and an
exact-match rule would miss it. The cost is over-redaction: a field called
`token_count` loses a harmless integer. That trade is taken knowingly, and it is
the right way round — redacting a number nobody needed is an inconvenience,
printing a live API secret is not.

Redaction descends into nested mappings and sequences, because a secret one
level down is still a secret. It stops after eight levels and replaces whatever
it finds there instead of rendering it: a structure that deep inside a log field
is already a mistake, and a value nobody has inspected must not be emitted. The
same limit is what terminates redaction on a self-referential structure.

Strings are not descended into as sequences. Doing so would redact a password
one character at a time, which is to say not at all.

### Redacted name fragments

- `api_key`
- `apikey`
- `authorization`
- `cookie`
- `credential`
- `passphrase`
- `password`
- `private_key`
- `secret`
- `session_id`
- `signature`
- `token`

This is a mechanism with a defensible starting list, not GLOBIN's secret
inventory. Phase 015 established the security baseline —
[`security/SECURITY_BASELINE.md`](security/SECURITY_BASELINE.md) and
[ADR-0048](adr/0048-a-secret-lives-outside-the-tree-and-is-redacted-before-a-record-exists.md)
— and this list is where the field-name half of that policy lands. The baseline
requires redaction to happen while the record is constructed rather than at any
sink, which is what this list implements; adding a fragment here is how that
policy is extended.

---

## Failure behaviour

**A value JSON cannot represent is rendered, never refused.** A `Decimal`, an
exception object or a custom class is written as its `repr`. Coercion is total,
so a logging call cannot raise. The cost is that a type with an unhelpful `repr`
logs unhelpfully rather than loudly; the alternative is a diagnostic that can
stop the work it was describing, which from Phases 081-096 means an order loop.

Non-finite floats are written as text, because `NaN` and `Infinity` are what
JSON serialisers emit for them and neither is valid JSON for anything that later
reads the file back.

**A failed write propagates.** The stream is not wrapped, so a closed pipe or a
full disk surfaces at the call site rather than disappearing.
[`ENGINEERING_CONTRACT.md`](engineering/ENGINEERING_CONTRACT.md) invariant 23
forbids swallowing an exception silently, and a sink that quietly discards
records is indistinguishable from a working one right up until you need the log.

That is the correct behaviour for the stream sink, not a claim about every sink.
A caller that must survive a broken log stream is served by a decorating sink
that degrades deliberately and reports that it did — an addition behind the same
port, not a change to this one.

---

## What a change to logging must satisfy

- Fields carry values; messages carry no interpolation.
- A new sink implements the port and inherits redaction; it does not re-implement it.
- A new redacted fragment is added in `observability.py` **and** to the list above.
- Severity is chosen from the table, not from how the code path felt to write.
- Nothing configures logging at import time — see
  [`architecture/README.md`](architecture/README.md).

---

## Related documents

- [`ENGINEERING_CONTRACT.md`](engineering/ENGINEERING_CONTRACT.md) — invariants 10, 23 and 24.
- [`architecture/README.md`](architecture/README.md) — why only the outer layers may log.
- [`TESTING_STRATEGY.md`](TESTING_STRATEGY.md) — where a logging test belongs.
- [`adr/0025-structured-logging-is-a-redacted-domain-event.md`](adr/0025-structured-logging-is-a-redacted-domain-event.md)
- [`adr/0026-correlation-is-bound-explicitly-not-ambiently.md`](adr/0026-correlation-is-bound-explicitly-not-ambiently.md)
