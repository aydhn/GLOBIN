# Configuration Policy

How GLOBIN is configured, what may be configured, and what happens when a
document is wrong.

This document is the settings register. The table below and
[`src/globin/domain/configuration.py`](../src/globin/domain/configuration.py)
are compared by `tests/contract/test_configuration_contract.py`, so a setting
that exists in one and not the other fails the suite rather than drifting
quietly.

---

## What a configuration is

A **setting** is one named, typed value an operator may vary. A **section**
groups the settings belonging to one subsystem. A **configuration layer** is one
source's contribution — a flat set of dotted keys, plus an **origin** naming
where they came from. **Precedence** is the rule that decides which layer wins
when two set the same key.

The model is a frozen dataclass. There is no configuration object in a
half-built state, because the only way to obtain one is to hand a resolved set
of settings to a function that validates them first. GLOBIN carries no schema
library to do this: [ADR-0003](adr/0003-zero-budget-open-source-dependency-policy.md)
makes the empty runtime dependency list an invariant, and the dataclass is the
schema in any case — the key register and the defaults are both derived from it,
so a new setting is one line and cannot be half-added.

---

## Settings

| Key | Type | Default | Meaning |
|---|---|---|---|
| `logging.min_severity` | `Severity` | `DEBUG` | The lowest severity a sink keeps. Records below it are discarded. |
| `logging.rotation_max_bytes` | `int` | `1048576` | The size at which the runtime log file is rotated. Between 4096 and 67108864. |
| `logging.rotation_backup_count` | `int` | `7` | How many rotated log files are kept beside the live one. Between 0 and 32. |
| `diagnostics.minimum_free_bytes` | `int` | `268435456` | Free space on a runtime filesystem below which the disk check fails. Between 1 MiB and 1 TiB. |
| `diagnostics.disk_warning_bytes` | `int` | `1073741824` | Free space below which it warns. Must be above the failure threshold. |
| `diagnostics.minimum_available_memory_bytes` | `int` | `134217728` | Available host memory below which the memory check fails. |
| `diagnostics.process_rss_warning_bytes` | `int` | `1073741824` | This process's resident set above which the process-memory check warns. Never a failure. |
| `diagnostics.budget_millis` | `int` | `5000` | How long a whole health snapshot may take. Between 50 and 60000. |
| `diagnostics.bundle_total_input_bytes` | `int` | `67108864` | How much may be read from disk into one support bundle. |
| `diagnostics.bundle_archive_bytes` | `int` | `33554432` | How large the finished bundle may be. Between 4 KiB and 256 MiB. |
| `diagnostics.bundle_member_bytes` | `int` | `8388608` | How large one member may be before it is truncated and marked truncated. |
| `diagnostics.bundle_log_bytes` | `int` | `16777216` | How much log text a bundle may include in total. |
| `diagnostics.bundle_member_count` | `int` | `64` | How many members a bundle may hold. Between 1 and 512. |
| `diagnostics.tracemalloc_enabled` | `bool` | `false` | Whether the interpreter's allocator tracer runs. |
| `diagnostics.tracemalloc_frame_depth` | `int` | `8` | How many frames each traced allocation retains. Between 1 and 64. |
| `diagnostics.tracemalloc_top` | `int` | `10` | How many allocation sites a memory summary reports. Between 1 and 64. |
| `watchdog.enabled` | `bool` | `true` | Whether the liveness watchdog runs at all. |
| `watchdog.interval_millis` | `int` | `1000` | How often it looks. Between 100 and 60000. |
| `watchdog.grace_millis` | `int` | `5000` | How long start-up is given before anything is judged. Between 0 and 600000. |
| `watchdog.stall_millis` | `int` | `30000` | How long a required component may be silent. Between 1000 and 3600000, and above the interval. |
| `watchdog.escalate_millis` | `int` | `15000` | How long after that the process has to stop itself. Between 1000 and 600000, and not below the interval. |
| `watchdog.escalation_enabled` | `bool` | `true` | Whether the process is ended when it does not stop itself. |
| `telemetry.enabled` | `bool` | `true` | Whether measurements are recorded at all. |
| `telemetry.export_enabled` | `bool` | `false` | Whether anything is handed to an exporter. Off by default, and the default is the posture: with it off no exporter, queue, pump or thread is constructed. |
| `telemetry.queue_capacity` | `int` | `256` | The most batches held before dropping starts. Between 1 and 4096. |
| `telemetry.batch_size` | `int` | `32` | The most documents handed over in one attempt. Between 1 and 4096, and not above the queue capacity. |
| `telemetry.flush_millis` | `int` | `5000` | How often the exporter loop wakes. Between 100 and 300000. |
| `diagnostics_http.enabled` | `bool` | `false` | Whether the loopback diagnostics surface binds a socket at all. Off by default, and the default is the posture: with it off no server, socket, queue or worker thread is constructed. |
| `diagnostics_http.bind_host` | `str` | `127.0.0.1` | Which loopback address it binds. Validated as a loopback address by `ipaddress`, so a wildcard, a LAN address and a hostname are all refused. `::1` is the other accepted value. |
| `diagnostics_http.port` | `int` | `9464` | Which port it binds. Between 1024 and 65535. |
| `diagnostics_http.request_timeout_seconds` | `int` | `5` | How long one request may occupy a worker. Between 1 and 60. |
| `diagnostics_http.shutdown_timeout_seconds` | `int` | `5` | How long in-flight requests get to finish during an orderly stop. Between 1 and 60. |
| `diagnostics_http.max_concurrent_requests` | `int` | `4` | How many requests may be in flight at once, which is also how many worker threads exist. Between 1 and 64. |
| `diagnostics_http.max_response_bytes` | `int` | `1048576` | The largest body it will send. Between 1024 and 8388608. |
| `diagnostics_http.diagnostics_snapshot_enabled` | `bool` | `false` | Whether the snapshot route answers. Off even when the surface is on. |
| `diagnostics_http.metrics_enabled` | `bool` | `true` | Whether the scrape route answers. |
| `diagnostics_http.health_enabled` | `bool` | `true` | Whether the three health routes answer. |
| `auth.key_type` | `str` | `` | Which API key type is enrolled: `hmac`, `rsa` or `ed25519`. **Empty means not configured**, and there is deliberately no default — see below. |
| `auth.recv_window_millis` | `str` | `5000` | How long a signed request stays valid, in milliseconds. **A quoted string, not a number.** Up to three decimal places, and never above 60000. |
| `auth.timestamp_unit` | `str` | `milliseconds` | Which unit the `timestamp` parameter carries. `milliseconds` or `microseconds`. |
| `auth.probe_enabled` | `bool` | `false` | Whether the authenticated read-only probe may run at all. |
| `auth.allow_production_probe` | `bool` | `false` | Whether it may run against the live exchange. Separate from the switch above on purpose. |
| `clock.sample_count` | `int` | `5` | How many calibration samples the window keeps per clock domain. Between 1 and 16. |
| `clock.freshness_ttl_millis` | `int` | `300000` | How long a calibration stays fresh enough to sign with. Between 1 and 86400000. |
| `clock.degraded_grace_millis` | `int` | `900000` | How long a surviving sample keeps a domain describable after a probe fails. Never admits a signature. |
| `clock.max_round_trip_millis` | `int` | `2000` | The slowest round trip a usable sample may have. |
| `clock.max_uncertainty_millis` | `int` | `250` | The widest error bound an admitted timestamp may carry. Must stay under the venue's 1000ms future tolerance. |
| `clock.max_offset_jump_millis` | `int` | `1000` | How far the estimated offset may move between calibrations before it is disbelieved. |
| `clock.max_wall_divergence_millis` | `int` | `500` | How far the host's wall clock may diverge from its monotonic clock before a jump is declared. |
| `clock.network_budget_millis` | `int` | `1000` | The unobservable delay a signed request is assumed to meet, spent against `recvWindow`. |
| `clock.require_calibration` | `bool` | `true` | Whether this host is expected to reach a venue clock at all. **Turning it off does not permit signing against an unsynchronised clock.** |

Fifty-one settings in seven sections. Of everything Phases 001-006 built, only
logging held anything an operator may reasonably change: the project contract and
the roadmap are immutable identity, the error taxonomy has nothing to tune, and
the architecture review's paths are constants rather than settings. Phase 023
added the two rotation values when it gave GLOBIN somewhere to write, and Phase
024 added the `diagnostics` section — the first second section this register has
had. Phase 025 added `watchdog`, which is the third.

Phase 035 added `auth`, which is the sixth, and two of its five rows deserve a
note because they break a pattern every row above follows.

**`auth.key_type` has an empty default, and that is a refusal rather than an
oversight.** Every other setting here declares the value GLOBIN uses when nobody
says otherwise. This one cannot: a default would name an algorithm, it would apply
to whatever secret happened to be enrolled, and the obvious choice — HMAC — is the
one the venue's own API Key Types document calls deprecated. Empty produces a
refusal naming what to enrol, which is the honest answer to *nobody has configured
this*.

**`auth.recv_window_millis` is a quoted string where every other numeric setting
is a number.** The venue documents *"up to three decimal places of precision
(e.g., 6000.346)"*, and `6000.346` is not representable as a binary float — a TOML
float would have changed the value before any type in this repository could refuse
it, and a TOML integer could not express it at all. So the operator's own
characters are stored and parsed to a `Decimal` at the point of use.
`auth.recv_window_millis = 6000.346` is refused with a message about the type.

**Phase 027 added `diagnostics_http` and removed two rows.** `telemetry.listener_enabled`
and `telemetry.listener_port` described a scrape endpoint that nothing ever started,
serving a registry GLOBIN never populated. The endpoint exists now, it serves health
as well as metrics, and its settings are in the section named after it. Two ways to
open a socket — one working, one dormant — would have been the second independent
source of truth this repository refuses.

**`bind_host` is the one row where a *setting* replaced a *literal*, and that is a
change of instrument rather than a relaxation.** Phase 026 exposed no address at all,
reasoning that a configurable one is a typo away from publishing this process's
internals. The danger was real and the instrument was wrong: a literal keeps the
address safe while making `::1` unreachable, and it puts the guarantee in a constant
somebody can edit. What replaced it is a value type — `LoopbackAddress` refuses
anything `ipaddress` does not call loopback — so the field cannot *hold* an address
another machine could reach, and the refusal covers spellings no denylist would have
enumerated. ADR-0072 records the exchange.

**The `watchdog` section is six rows where thirteen were available, and what it
leaves out is the point.** How many threads a stall dump describes, how many frames
of each, and how large the whole dump may be are all bounds this phase chose — and
they live in `src/globin/domain/watchdog.py` as constants, on the precedent
`TRACEBACK_LIMIT` set in Phase 023. They are there rather than here because no
operator has a basis for preferring twenty-four frames to thirty-two: the number
exists so a record stays readable, which is a decision, not a policy. The exit code
a termination leaves is absent for a sharper reason — a configurable one could be
set to `0`, which would tell a launcher that a process the watchdog killed had
succeeded.

**Two of the six are the interval, used twice.** `watchdog.interval_millis` says
how often the watchdog looks *and* defines what a first missed beat is, which is
why `suspect` has no threshold of its own. A fourth duration would have had to
justify itself, and "we looked, and it had not moved since last time" is already
the natural meaning of a first warning.

**Both switches default to `true`, and that is the opposite of
`diagnostics.tracemalloc_enabled`.** Tracing defaults off because it costs the
whole process to produce a diagnostic nobody asked for. A watchdog costs one thread
waiting on an event, and a safety mechanism nobody switched on protects nobody.
`watchdog.escalation_enabled` is the narrower switch: turning it off keeps the
detection, the evidence and the graceful request, and stops only at the
termination — which is what an operator wants while they are still learning what
their own thresholds mean on their own host.

**Thirteen at once is a lot, and the alternative was worse.** Each is a number a
health check or a bundle limit compares a measurement against, and the only other
home for such a number is a literal at the comparison — which is exactly the magic
constant an operator cannot change and a reader cannot find. None is speculative:
every one has a call site in the phase that added it, which is the test this
document asks a new setting to pass.

**`diagnostics.tracemalloc_enabled` defaults to `false`, and that default is
load-bearing rather than cautious.** Tracing costs the whole process on every
allocation, in every thread, until it is switched off. A runtime that enabled it
because the setting existed would be paying a profiler's price to populate a
diagnostic nobody asked for.

**The first `bool` in the register is read more strictly than Python would.**
`bool(value)` treats `"false"` as true, which is not a corner case: it is the
single most likely thing an operator writes when they want tracing off, and it
would silently turn the profiler on. Only `true` and `false` are accepted, in any
case — not `1`, not `"yes"`, not `"on"`. A value with several spellings has
several ways to be typed wrong, and each of them fails in the permissive
direction.

**Two of these are checked against each other rather than only against their own
range.** `disk_warning_bytes` must be strictly above `minimum_free_bytes`, or the
check can never warn: it fails first, and the warning band an operator configured
has silently zero width. Every individual value would be in range, so nothing else
would report it.

**The two integers are bounded, and refused twice.** `as_config` refuses an
out-of-range value with a message naming the document it came from, because that
is what an operator needs; `RotationPolicy` refuses it again on construction,
because a policy that cannot be honoured must not exist. Neither gate is
redundant — the first exists to explain, the second to guarantee. A `bool` is
refused for both, even though Python makes it an `int`: `true` resolving to a
rotation size of one byte is the kind of accident that looks like it worked.

A configuration model is exactly where speculative fields accumulate, so the
register grows in the phase that needs the setting and not before —
[`engineering/REPOSITORY_LAYOUT.md`](engineering/REPOSITORY_LAYOUT.md) refuses
the same thing for directories, and for the same reason.

The default discards nothing. That is deliberate twice over: it leaves Phase
006's behaviour exactly as it was for a caller who configures nothing, and
[`engineering/ENGINEERING_CONTRACT.md`](engineering/ENGINEERING_CONTRACT.md)
invariant 22 makes discarding data an explicit decision rather than something
GLOBIN does on an operator's behalf.

### Spelling

A severity is written as its name, in capitals, exactly as
[`LOGGING_POLICY.md`](LOGGING_POLICY.md) spells it. Two refusals follow from
that and are worth stating, because both look unhelpful until the reason is
visible:

- **A number is not accepted**, even though severities are ordered integers
  internally. `25` names no level, and a threshold that silently means
  "somewhere between two levels" is worse than one that refuses.
- **Case is exact.** `warning` is refused. One spelling means one thing to
  search for, and the refusal message enumerates the accepted names, so a
  rejected document tells the operator what to write instead.

---

## Precedence

Layers are folded weakest first, strongest last. **The last layer that mentions
a key wins.**

Three consequences define the mechanism:

- **Silence is not a value.** A layer that says nothing about a key leaves the
  answer it already had. There is no unset sentinel, so a layer may replace a
  setting but can never delete one.
- **An empty layer changes nothing.** A source with nothing to say still returns
  a layer, so no caller needs a special case for it.
- **Applying the same layer twice is the same as applying it once.**

Keys are flat and dotted rather than nested. A nested merge would have to answer
whether a table replaces its counterpart or merges into it, and every answer to
that question surprises somebody; flattening removes the question.

**Phase 030 was asked for a recursive deep merge and refused it, on that reasoning
rather than on inertia.** The request came with the rest of that phase's brief, and
what it would have bought — nested tables merging into one another — is exactly the
ambiguity the paragraph above removes. What it would have cost is every one of the
thirty-seven settings, `resolve`, `as_config` and their contract tests rewritten to
serve a shape no document in this repository uses. The refusal is recorded here so
that a later phase proposing it again starts from the argument rather than from the
absence of one.

**Phase 030 added a source at each end**, and the order is not a fifth judgement: it
is the same rule the four already followed, which is **narrowness**. A committed
document applies to every invocation; an explicit `--config` document to every
invocation that names it; an environment variable to a shell session; a `--set` flag
to exactly one run. The narrowest act wins, because it is the one somebody performed
most deliberately and the one whose result they are most likely to be watching.

| # | Source | Origin | Phase |
|---|---|---|---|
| 0 | Typed code defaults | `defaults` | 007 |
| 1 | `config/globin.toml` | its path | 026 |
| 2 | `config/profiles/<profile>.toml` | its path | 026 |
| 3 | `config/local/globin.toml` | its path | 026 |
| 4 | `config/local/profiles/<profile>.toml` | its path | 026 |
| 5 | `--config PATH` | its absolute path | 030 |
| 6 | `GLOBIN_*` environment variables | `environment` | 027 |
| 7 | `--set KEY=VALUE` | `command line` | 030 |

**Only keys an operator actually typed enter the command-line layer.** A parser
default reaching the strongest source would make it set every setting on every run,
and no document below it could ever win — the failure a highest-priority overlay has
to be built to avoid rather than to document.

Which source won each key, and how many were overruled on the way, is answerable
since Phase 030: [`engineering/CONFIGURATION_EVIDENCE.md`](engineering/CONFIGURATION_EVIDENCE.md).

---

## Refusal

Refusal happens once, when resolved settings are bound to the model, because
that is the only point where both the schema and the origin of each value are
known. The fold itself never refuses anything and never raises.

| Situation | Error | Who acts |
|---|---|---|
| A key that is not a setting | `ConfigurationError` | The operator. Every unknown key is named at once, so fixing one does not merely reveal the next. |
| A value its setting cannot read | `ConfigurationError` | The operator. The message names the key, the value and the document. |
| A key containing a `.` through quoting | `ConfigurationError` | The operator. Flattened, it could not be told apart from a table. |
| A layer with no origin, or one key set twice | `ValidationError` | The caller. Within one document a repeated key has no defensible reading. |
| A document that is not valid TOML | `TOMLDecodeError` | The operator. Left unwrapped, because the line and column are worth more than a reworded message. |
| A known setting with no resolved value | `InternalError` | Nobody: this is a GLOBIN defect, reachable only by resolving without the defaults. |
| A `--set` argument carrying no `=` | `ConfigurationError` | The operator. An override is written `key=value`. |
| A `--set` key that is not a setting | `ConfigurationError` | The operator. The registry it is checked against is `known_keys()`, so there is no arbitrary path to accept. |
| A `--set` key that is credential-shaped | `ConfigurationError` | The operator. Refused on the *name*, so the value is never read and never appears in the message. |
| The same `--set` key twice | `ConfigurationError` | The operator. One override per setting. |
| A document named by `--config` that is not there | `ConfigurationError` | The operator. Unlike the four computed documents, a named one must exist: GLOBIN will not start on values nobody chose. |
| A document larger than the declared ceiling | `ConfigurationError` | The operator. Almost always a path naming something that is not a configuration file. |
| A document declaring an unsupported `config_schema_version` | `ConfigurationError` | The operator. Refused in both directions; there is no migration engine and nothing is upgraded silently. |

**An unknown key is refused, never ignored.** A typo that silently disables a
setting an operator believes they have set is the failure this whole mechanism
exists to prevent, and a configuration system that shrugs at keys it does not
recognise provides no such guarantee.

**A value that a stronger layer replaces is not validated.** Every source is
still read, so a broken document is reported wherever it sits in the order, and
an unknown key always survives the fold. But a layer exists precisely so that a
stronger one may replace what it said, and a value that has been replaced has no
effect to be wrong about. The behaviour is held in place by
`tests/integration/test_configuration_end_to_end.py` so that changing it later
is a decision rather than a regression.

---

## What this does not cover

| Question | Phase |
|---|---|
| Where configuration files live, what they are called, and what profiles exist | 026, delivered — [`engineering/CONFIGURATION_LAYOUT.md`](engineering/CONFIGURATION_LAYOUT.md) |
| Which sources are consulted, in what order, and how environment variables and launcher selection fit | 027, delivered — the `Precedence` section above, and [ADR-0071](adr/0071-configuration-precedence-is-declared-and-an-environment-variable-is-a-derived-name.md) |
| Which source won a given key, what the resolution digests to, and what changed since last time | 030, delivered — [`engineering/CONFIGURATION_EVIDENCE.md`](engineering/CONFIGURATION_EVIDENCE.md) |
| The rules a secret is handled under | 015, delivered — [`security/SECURITY_BASELINE.md`](security/SECURITY_BASELINE.md) |
| Where a secret is stored, and how it is supplied | 028, delivered — [`security/SECRET_STORE.md`](security/SECRET_STORE.md) |
| How a credential is collected from an operator, and what it is permitted to do | 029, delivered — [`security/CREDENTIAL_FLOW.md`](security/CREDENTIAL_FLOW.md) |
| Which algorithm signs a request to a given surface | delivered at 035 — [`engineering/REST_AUTHENTICATION.md`](engineering/REST_AUTHENTICATION.md) |
| Whether a venue agrees a key carries the permissions declared for it | 039 |
| What an environment is, and how production, testnet and demo differ | 035, delivered — [`engineering/ENVIRONMENT_CLASSES.md`](engineering/ENVIRONMENT_CLASSES.md) |

Nothing in the configuration model knows about files, environment variables or
the machine it runs on. A source is handed a path; it never searches for one,
and it holds no default location. **Phase 026 answered where documents live
without weakening that**: `config/` exists and
[`engineering/CONFIGURATION_LAYOUT.md`](engineering/CONFIGURATION_LAYOUT.md)
*computes* a spelling from a layout and a profile rather than looking anything
up, because a search order is a precedence and precedence is Phase 027's.

---

## Adding a setting

1. Add a typed field, **with a default**, to the section's frozen dataclass. A
   setting that cannot resolve without a file makes the defaults incomplete, and
   is refused as a defect in the model.
2. Bind it in the function that builds the model from resolved settings.
3. Add a row to the table above. The contract test compares the two.
4. Cover the value's refusal path. A validator whose failing case is never
   exercised tends to quietly stop matching anything —
   [`TESTING_STRATEGY.md`](TESTING_STRATEGY.md) requires the failing case.

A new *section* additionally needs a field on the top-level model and its own
entry in the key register. Both are derived from the dataclass, so neither is a
second place to state the same thing.
