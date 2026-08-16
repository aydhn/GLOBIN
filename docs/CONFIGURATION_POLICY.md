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

Sixteen settings in two sections. Of everything Phases 001-006 built, only
logging held anything an operator may reasonably change: the project contract and
the roadmap are immutable identity, the error taxonomy has nothing to tune, and
the architecture review's paths are constants rather than settings. Phase 023
added the two rotation values when it gave GLOBIN somewhere to write, and Phase
024 added the `diagnostics` section — the first second section this register has
had.

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
| Where configuration files live, what they are called, and what profiles exist | 026 |
| Which sources are consulted, in what order, and how environment variables and launcher selection fit | 027 |
| The rules a secret is handled under | 015, delivered — [`security/SECURITY_BASELINE.md`](security/SECURITY_BASELINE.md) |
| Where a secret is stored, and how it is supplied | 028 |
| What an environment is, and how production, testnet and demo differ | 035 |

Nothing in the configuration model knows about files, environment variables or
the machine it runs on. A source is handed a path; it never searches for one,
and it holds no default location. That is why the `config/` directory still does
not exist — creating it would settle Phase 026's question by accident.

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
