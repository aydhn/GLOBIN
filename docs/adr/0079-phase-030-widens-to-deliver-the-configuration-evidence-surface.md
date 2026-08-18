# ADR-0079: Phase 030 widens to deliver the configuration evidence surface

## Status

Accepted — Phase 030.

**Date:** 2026-08-18

## Context

`ROADMAP.md` row 030 reads *Bootstrap Health Check Suite*: "Implement the preflight
checks that must pass before any long-running GLOBIN process starts."
[`MEMORY.md`](../../MEMORY.md) records what it inherits — an eighteen-check registry
in `globin.domain.bootstrap.checks()`, to which Phase 029 added the eighteenth
through the extension point Phase 021 built, "and proposed no suite, no scheduling
and no periodicity, all of which are 030's."

The phase brief asked for something else: a typed layered runtime configuration
contract with deterministic source precedence, TOML, environment and CLI overlays,
strict validation, provenance and drift evidence. Read against this repository,
most of that names work that is **already delivered**. Phase 007 built the typed
model and the fold; Phase 026 the on-disk layout and the four profiles; Phase 027
the precedence between defaults, documents, the environment and launcher selection.
Five of the brief's six precedence layers run today, and
[ADR-0071](0071-configuration-precedence-is-declared-and-an-environment-variable-is-a-derived-name.md)
records the reasoning for their order.

Three things in it are not delivered, and each is a hole somebody would eventually
fall into:

1. **`config.valid` says one sentence.** `application/bootstrap.py` binds the model
   and reports `"bound, logging at DEBUG"`, or one failure string. Of the eighteen
   checks the suite is made of, this is the one whose failure an operator is most
   likely to be able to fix — and it cannot say which document, which layer, or
   which of six sources supplied the value that refused.
2. **A stated limitation about the working directory.**
   [`CONFIGURATION_LAYOUT.md`](../engineering/CONFIGURATION_LAYOUT.md) says it
   outright: `find_project_root` walks up from the working directory, so an
   installed `globin` run from elsewhere finds no configuration, resolves declared
   defaults, and *reports nothing about having done so*.
3. **No command-line value layer.** `--profile` selects which documents are read.
   Nothing sets a value for one invocation.

The brief also asked for two things this repository has already decided against, and
they are refused here rather than absorbed. **Recursive deep merge of nested
mappings** is refused because [`CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md)
chose flat dotted keys precisely to remove the question a deep merge has to answer —
"does a table replace its counterpart or merge into it" — and every answer to that
question surprises somebody. **Six separate JSON evidence documents** are refused
because every area in this repository writes exactly one manifest, and
[`QUALITY_GATES.md`](../engineering/QUALITY_GATES.md) records that a second upload
path broke a CI job in Phase 015.

## Decision

Phase 030 delivers its titled scope in full, and additionally delivers the
configuration evidence surface. The amendment covers **only the second half**: the
preflight suite, its classification and its schedule are row 030's own words and are
not amended scope.

The titled half:

- Every registered check declares a `Durability` — whether its answer survives the
  run — with `PERISHABLE` as the conservative default. Eleven of the eighteen are
  stable.
- A `RecheckPolicy` declares how often a perishable answer is taken again, and
  cannot be constructed at an interval no scheduler could honour.
- `bootstrap preflight` runs every check *and* gates, and reports how long its
  verdict stays true.

The amended half:

- A command-line value layer, `--set KEY=VALUE`, above the environment. Keys are
  validated against `known_keys()`, which is derived from the dataclasses, so there
  is no arbitrary path to accept.
- `--config PATH`, an explicit document above the four computed ones and below the
  environment, resolved to an absolute path, and **fatal when absent** where the
  four are optional.
- Per-field provenance: the winning origin, its priority, and how many weaker
  layers it overruled.
- `config_schema_version` as a reserved document key, refused in both directions.
- A bounded document size.
- A second fingerprint that includes origins, held apart from the semantic one that
  excludes them.
- A drift comparison against a recorded baseline, where no baseline is `unmeasured`
  rather than clean.
- One manifest, `.globin/config/config-manifest.json`, carrying the six documents
  the brief named as six sections.

**What this does not cover.** No hot reload, no migration engine, no wizard, and no
secret in configuration. Nothing here executes a periodic re-take: GLOBIN has no
long-running process, so the schedule is declared and validated rather than run.

### Scoring ADR-0021's four conditions

[ADR-0021](0021-phase-005-widens-to-include-the-test-foundation.md) permits an
amendment that can say four things. This record argues them from its own evidence.
[ADR-0076](0076-phase-029-widens-to-deliver-the-dependency-attestation.md) closes by
saying a fourteenth inherits nothing from it, may not cite it, and may not cite the
amendment count; and [ADR-0070](0070-phase-027-widens-to-deliver-the-loopback-diagnostics-surface.md)
adds that no amendment may cite the owner's having overridden the refusal once.
Neither is cited in support below.

| Condition | Verdict |
|---|---|
| Nothing displaced | **Passes.** The configuration layout is Phase 026 and its precedence is Phase 027. Both are `Complete`, and a completed phase cannot be displaced. |
| Nothing deferred | **Passes.** The bootstrap health check suite ships whole, in the same commit. |
| No phase owns the work | **Passes**, with two boundaries stated below. |
| The two halves need each other | **Passes.** `config.valid` is one of the eighteen checks the suite is made of. |

**The two boundaries, named rather than assumed.** Phase 291 *Interactive
Configuration Wizard* owns **collecting** configuration an operator has not
supplied, with validation and safe defaults; nothing here collects anything, and
`tomllib` cannot write, so this phase is structurally incapable of it. Phase 283
*Backup and Restore Procedures* owns backing configuration up. Neither owns
explaining a resolution that already happened.

**Phase 297 is the boundary worth stating twice**, because its title is *Preflight
Verification Gate* and this phase adds a command called `preflight`. They are not
the same gate. Phase 297 blocks a **live launch** on environment, credentials,
**connectivity** and **risk**; this phase's suite is local, reaches no network, and
knows nothing about risk. Phase 297 is also not displaced by the classification: it
inherits it, exactly as this phase inherited `checks()`.

**This scores four of four, and the score is reported rather than leaned on.** It is
the first amendment to do so. It does not answer the granularity question that
[ADR-0064](0064-phase-025-widens-to-deliver-the-runtime-watchdog.md) raised and
ADR-0067 recorded as fired, which remains Phase 032's with fourteen amendments in
front of it. What it contributes to that review is a data point rather than an
argument: an amendment satisfying every condition was available inside a band whose
granularity is under review, which is evidence about where the phase boundary was
drawn rather than about the test.

## Consequences

**What this costs.**

- The command line grows a fifth top-level word and two options that every
  configuration-resolving command now accepts. Four options where there were two is
  more surface to keep consistent, and `_options` returns a record rather than a
  tuple because four positional values is where a caller starts unpacking them in
  the wrong order.
- `build_config_sources` and `build_bootstrap` each grew two keyword parameters.
  Both default to `None`, so no existing caller changed, but the chain is now
  assembled from six kinds of input rather than four.
- A second digest exists over the same configuration. Two fingerprints is one more
  thing to explain, and the explanation — that they answer different questions and
  disagree exactly where they should — has to be carried in the documentation
  rather than inferred.
- Every field now carries a digest of its real value. That is a per-field hash on
  every resolution, and it is what makes drift work on fields a redacted display
  would hide.

**What is now prohibited that a contributor might reasonably want.**

- A second parser. The hand-written one refuses abbreviation by construction, and
  adding `argparse` for the new options would reintroduce `allow_abbrev` as
  something to remember.
- Six evidence files. The sections are sections.
- A settings row for the re-take interval. `CONFIGURATION_POLICY.md` asks a
  proposed setting to have a call site in the phase that adds it, and this one has
  none.

**What enforcement exists.** `tests/unit/test_preflight.py`,
`tests/unit/test_config_evidence.py`, `tests/unit/test_config_cli.py` and
`tests/integration/test_config_evidence_end_to_end.py`, plus the contract tests that
compare the documented tables against the code in both directions. The
classification is derived from `checks()` rather than restated, so a renamed check
cannot leave a stale entry.

## Alternatives Considered

**Deliver the titled scope alone, and record the configuration work as deferred.**
This was the smallest honest option and it was put to the owner as one of four. It
was not chosen because the second half is not adjacent work that happened to be
nearby: the check whose reporting it improves is one of the eighteen the phase is
about. Its cost is real, though — a phase that delivers one thing is easier to
review than one that delivers two, and this record does not pretend otherwise.

**Treat the whole brief as the phase and rewrite row 030.** Refused. It would have
left the bootstrap health check suite undelivered while the roadmap said Phase 030
was complete, which is the one failure the status column exists to prevent.

**Treat the configuration work as repair of Phases 026 and 027 rather than an
amendment.** Tempting, because two of the three holes are things those phases left.
Refused because a completed phase is completed: reopening one to absorb new work
would make "Complete" mean "complete except for whatever a later phase decides to
file here", and the amendment ledger exists precisely so that widening is visible.

**Route it through [ADR-0032](0032-verification-tooling-may-be-added-outside-phase-scope.md)'s
six conditions instead.** Refused on condition 4 — "adds no runtime capability".
This adds several. Phases 028 and 029 declined the same route for the same reason,
which is a precedent about the condition rather than a citation in support.

**Use `argparse` for the widened option set.** Refused. Its `allow_abbrev` defaults
to `True`, so deterministic behaviour would depend on remembering to switch a flag
off; the hand-written parser compares every word for equality and has no prefix
logic to disable.

## Risks and Trade-offs

**The characteristic failure mode of this choice is that the amendment test stops
discriminating.** Thirteen amendments scored one or two of four and were taken
anyway; this one scores four. The risk is that a fourteenth passing cleanly reads as
evidence the test works, when the more likely reading is that the band's phases are
drawn at a granularity where almost any adjacent work can be argued into one of
them. **The observable signal is a fifteenth amendment citing this record's score as
precedent** — which this record forbids, in the same terms ADR-0076 used on it.

**The second characteristic failure is a shelf life nobody honours.** The re-take
schedule is declared and validated, and nothing executes it, because nothing runs
long enough to need it. The signal that this was wrong is a later phase starting a
long-running process and building its own re-check loop rather than reading
`RecheckPolicy` — at which point the policy is a constant with a test and no reader.

**A third, smaller one: the field digest.** It is safe in the direction that matters
— an unguessable value stays unguessable — and reversible for a boolean, which is
not a secret. If configuration ever did carry something low-entropy and sensitive,
the digest would be a disclosure. `SECURITY_BASELINE.md` says that cannot happen,
and `EnvironmentConfigurationSource` refuses a credential-shaped name before reading
its value; the risk is stated because both of those are rules rather than
mechanisms.

**Confidence.** Moderate-to-high on the titled half, which is a classification and a
bounded policy over machinery that already existed. Moderate on the split between
the two fingerprints: it is the right split for the two questions asked today, and
whether operators actually ask the second one is not something this phase can know.

## References

- [ADR-0021](0021-phase-005-widens-to-include-the-test-foundation.md) — the
  four conditions.
- [ADR-0071](0071-configuration-precedence-is-declared-and-an-environment-variable-is-a-derived-name.md)
  — the precedence this extends at both ends.
- [ADR-0080](0080-a-check-declares-whether-its-answer-survives-the-run.md) — the
  titled half's decision.
- [ADR-0081](0081-configuration-explains-itself-through-two-fingerprints-and-one-manifest.md)
  — the amended half's decision.
- [`ROADMAP.md`](../../ROADMAP.md) — the ledger entry.
- [`docs/research/phase_030_sources.md`](../research/phase_030_sources.md) — what
  was read and what was measured.

## Supersedes

None.

## Superseded By

None.
