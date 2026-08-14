# ADR-0027 — Configuration is a frozen dataclass validated at one boundary, and the dataclass is the schema

## Status

Accepted — Phase 007.

**Date:** 2026-08-14

## Context

[`ROADMAP.md`](../../ROADMAP.md) assigns Phase 007 the typed configuration model,
its validation rules, its defaults and its layered override precedence. Six
places in the repository already pointed here for it, one of them production
code: [`architecture/README.md`](../architecture/README.md),
[`engineering/ENGINEERING_CONTRACT.md`](../engineering/ENGINEERING_CONTRACT.md),
[`engineering/REPOSITORY_LAYOUT.md`](../engineering/REPOSITORY_LAYOUT.md),
[`LOGGING_POLICY.md`](../LOGGING_POLICY.md), [ADR-0015](0015-single-composition-root-and-no-import-time-side-effects.md),
and the module docstring of `src/globin/domain/observability.py`.

Two constraints shaped the answer before any design work began.

**No dependency was available.** [ADR-0003](0003-zero-budget-open-source-dependency-policy.md)
makes the empty runtime dependency list an invariant, and
`tests/contract/test_packaging_contract.py` asserts it. Pydantic and its
relatives were never candidates. This is a constraint, but the design below is
not a workaround for it — see *Alternatives Considered*.

**No module-level work was available either.**
`tests/architecture/test_architecture_contract.py` fails any layer package
performing a call at import, and it follows class bodies. That rules out
`field(default_factory=...)`, `frozenset({...})`, `auto()` and a nested dataclass
default such as `logging: LoggingConfig = LoggingConfig()`. The shape of the
model is partly a consequence of that rule rather than of taste.

The remaining question was where validation lives. Phase 026 will add
configuration files and profiles, and Phase 027 will add environment variables
and launcher selection. Each is a new source. If a source validated what it
produced, each would carry its own copy of the rules, and copies of a validation
rule drift.

## Decision

**1. The model is frozen dataclasses, and the dataclass *is* the schema.**
`GlobinConfig` holds one field per section; each section is a frozen, slotted
dataclass whose fields are the settings. The key register and the defaults layer
are both derived from `dataclasses.fields()` — see
[S-01](../research/phase_007_sources.md) — so a setting exists in exactly one
place and cannot be half-added.

**2. Every setting declares a default.** A field whose default is `MISSING`
raises `InternalError`, because a setting that cannot resolve without a document
makes the defaults layer incomplete. That is a defect in the model, not in
anything an operator wrote.

**3. Validation lives in `globin.domain.configuration`, not in any adapter.**
Reading `"WARNING"` as a `Severity` is a domain rule. An adapter parses and
flattens; it never interprets. Phase 027's environment-variable source therefore
inherits these rules rather than restating them.

**4. Refusal happens once, at binding.** `as_config` is the only function that
rejects anything: an unknown key, or a value its setting cannot read. Both are
`ConfigurationError`, both name the key and the document, and every unknown key
is reported at once rather than one per run.

**5. An unknown key is refused, never ignored.** A typo that silently disables a
setting an operator believes they have set is the failure the model exists to
prevent.

**6. The default threshold discards nothing.** `Severity.DEBUG` is the lowest
member, so a caller who configures nothing sees exactly Phase 006's behaviour.
This is not in tension with "fail closed"
([`ENGINEERING_CONTRACT.md`](../engineering/ENGINEERING_CONTRACT.md) invariant 2),
which governs refusal on *ambiguity* — an unreadable severity raises. It says
nothing about which value a declared default should take, and invariant 22 makes
discarding data an explicit decision rather than a side effect.

**What this does not cover.** Where configuration files live, what they are
called and what profiles exist is Phase 026. Which sources are consulted and in
what order, including environment variables and launcher selection, is Phase 027.
Secret storage is Phase 015. Environment classification is Phase 035. The
`config/` directory is therefore still not created: doing so would settle Phase
026's question by accident.

## Consequences

- Adding a setting is one typed field with a default, one binding line, and one
  row in [`CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md). Forgetting the
  row fails `tests/contract/test_configuration_contract.py`, which compares the
  documented default by feeding it back through the binding rather than by
  comparing strings.
- The binding function grows one branch per setting. With a schema table it would
  not, and that cost is accepted: an explicit branch appears in a stack trace and
  is checked by `mypy`, and a table walked by reflection is neither.
- Nothing may be configured that no phase has yet designed. That is deliberate
  friction, and it will feel like an obstacle the first time somebody wants a
  quick flag.
- The model cannot carry a nested dataclass default, so `default_config()` is a
  function rather than a constant. A contributor who does not know why will try
  the constant, and the architecture test will tell them.
- Configuration is immutable, so nothing can reconfigure GLOBIN while it runs.
  Live reload, if it is ever wanted, becomes a new object handed to new work
  rather than a mutation — which is the property that makes a running trading
  loop's configuration knowable after the fact.

## Alternatives Considered

**A declarative field table** — `FieldSpec(name, kind, default, validator)`,
walked by a generic binder. Rejected on its own merits rather than because a
library was unavailable. To be typed at all the table has to be restated as a
dataclass, which is two definitions and a tripwire test to keep them equal; the
validators degrade to `Callable[[object], Any]`, so `mypy` stops checking the one
thing most worth checking; and it moves the model into something walked by
reflection, which [ADR-0015](0015-single-composition-root-and-no-import-time-side-effects.md)
rejected for the object graph for the same reason. Worth revisiting only when the
register is large enough that the per-setting branch is genuinely repetitive.

**Validation in the adapter.** Simpler today, because there is one adapter.
Rejected because there will be at least three sources by Phase 027, and the
second copy of a coercion rule is where the two spellings of a severity start to
diverge.

**Accepting an integer as a severity.** `min_severity = 30` reads naturally and
`Severity` is an `IntEnum`. Rejected: `25` names no level, and a threshold that
silently means "between two levels" is worse than one that refuses. `isinstance`
already gives this for free — see [S-03](../research/phase_007_sources.md).

**Accepting any case.** `"warning"` is what an operator will type first.
Rejected because one spelling means one thing to search a document for, and the
refusal message enumerates the accepted names, so the cost is one read of an
error message rather than an ambiguity that lasts.

**Ignoring unknown keys**, as many configuration systems do, on the grounds that
forward compatibility matters. Rejected: GLOBIN reads only documents written for
GLOBIN, so an unrecognised key is a mistake rather than a message from the
future.

## Risks and Trade-offs

The characteristic failure mode is a register that grows faster than the
reasoning behind it. A configuration model is the most inviting place in a
codebase to park a decision nobody wants to make — a boolean that turns something
off is much easier to add than an argument about whether it should exist. Applied
repeatedly, the model becomes a list of switches whose interactions nobody has
considered, which is exactly the state that makes a trading system's behaviour
unreproducible after the fact.

The observable signal is a setting whose row in
[`CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md) cannot say what an
operator would change it *for*, or a setting that weakens a guarantee rather than
selecting between two sound behaviours. `logging.redact_secrets` is the worked
example of the second kind and must never exist:
[`ENGINEERING_CONTRACT.md`](../engineering/ENGINEERING_CONTRACT.md) invariant 24
is absolute, and a boolean is a hole with a name on it.

A second, smaller risk: one section and one setting is a thin register, and a
reader may conclude the mechanism was over-built for it. The mechanism is the
deliverable the roadmap asked for, and the register's width is a fact about what
Phases 001-006 built rather than a judgement about what Phase 007 should have.

## References

- [`../CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md) — the settings
  register this record governs.
- [ADR-0003](0003-zero-budget-open-source-dependency-policy.md) — why no schema
  library was available.
- [ADR-0015](0015-single-composition-root-and-no-import-time-side-effects.md) —
  the composition rule, and the forward reference this record answers.
- [ADR-0022](0022-error-taxonomy-rooted-in-one-type.md) — the error categories
  the refusals use.
- [ADR-0028](0028-configuration-layers-override-last-wins-and-carry-their-origin.md)
  — the fold this record's binding consumes.
- [`../research/phase_007_sources.md`](../research/phase_007_sources.md) — the
  external evidence this phase relied on.

## Supersedes

None.

## Superseded By

None.
