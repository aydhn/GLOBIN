# ADR-0028 — Configuration layers are flat, override last-wins, carry their origin, and cannot remove a setting

## Status

Accepted — Phase 007.

**Date:** 2026-08-14

## Context

[`ROADMAP.md`](../../ROADMAP.md) gives Phase 007 "layered override precedence"
and Phase 027 "deterministic precedence between defaults, files, environment
variables and launcher selection". Those are two different jobs, and the boundary
between them is what this record fixes: Phase 007 owns the *algebra*, Phase 027
owns the *sources it is applied to*.

That split only works if the algebra knows nothing about where a value came
from. If the fold could tell a file from an environment variable, Phase 027 would
be editing the fold rather than supplying it, and every later source would be a
new special case inside a function that already has all the others.

A second pressure came from the failure mode configuration systems are known
for. When an operator says "I set that and it did not take effect", the answer is
almost never the value — they can read the value — but which of several documents
won, or whether the key was read at all.

## Decision

**1. A layer is flat.** `ConfigLayer` holds dotted keys mapped to values, not
nested tables. Flattening a document is the adapter's job.

**2. Layers are folded weakest first, and the last layer that *mentions* a key
wins.** This is the same override rule `Logger.bind` already uses, so the
repository has one such rule rather than two.

**3. Silence is not a value.** There is no unset sentinel. A layer may replace a
setting; nothing can delete one. `None` is a value like any other.

**4. An empty layer is the identity element**, at any position. A source with
nothing to say returns a layer with no values rather than `None`, so no caller
needs a special case.

**5. Every value carries its origin.** A `Setting` records which layer supplied
it, and every refusal message names that origin. The origin is a human-readable
label — a path, or `defaults` — not a type.

**6. The fold is total. It never raises.** It does not know the schema, so an
unknown key is carried through rather than rejected inside it. Refusal belongs to
[ADR-0027](0027-configuration-is-a-frozen-dataclass-validated-at-the-boundary.md)'s
binding step, where both the schema and the origin are in hand.

**7. A key that would flatten ambiguously is refused.** TOML permits a quoted key
containing a dot, and `"a.b" = 1` is one key while `[a]` with `b = 1` is a table —
see [S-05](../research/phase_007_sources.md). Flattened they collide, and there
is no resolution that is not a guess.

**8. A value a stronger layer replaces is not validated.** Every source is still
read, so a document that cannot be parsed is reported wherever it sits, and an
unknown key always survives the fold. But a layer exists precisely so a stronger
one may replace what it said.

**What this does not cover.** Which sources exist, in what order they are
consulted, and whether a missing one is fatal are Phase 027's decisions. This
record fixes what happens *given* an ordered sequence.

## Consequences

- Phase 027 adds sources without touching the fold. That is the point, and it is
  also the claim most worth checking when that phase arrives: if it needs to
  change `resolve`, one of these decisions was wrong.
- Deep merging is unavailable. An operator cannot add one key to a table another
  layer defined without the stronger layer restating the table — except that
  because keys are flat, they can: `logging.min_severity` is set independently of
  anything else under `logging`. The limitation is therefore theoretical for as
  long as no setting is itself a structure, and a setting that is a structure
  should be read as a sign that it wants to be several settings.
- Decision 8 is a real gap, stated rather than hidden: `min_severity = "LOUD"` in
  a document that something else overrides never reaches validation, and the typo
  survives until the day the override is removed. It is held in place by
  `tests/integration/test_configuration_end_to_end.py` so that changing it later
  is a decision rather than a regression.
- Because the fold is total, the property suite can assert that it is, over
  generated layers. That assertion fails the moment anyone adds a schema check
  inside it, which is the enforcement this record has.

## Alternatives Considered

**Nested layers with a deep merge.** Closer to how TOML documents are written.
Rejected because deep merge has to answer whether a table replaces its
counterpart or merges into it. Every answer surprises someone, and the surprise
lands on an operator reading a file rather than on a contributor reading code.

**An explicit unset sentinel**, so a stronger layer could remove a setting.
Rejected: it makes "the value is absent" and "the value is the sentinel" two
different states with one spelling, and there is no operator need for removal —
overriding to the default achieves everything removal would.

**Validating each layer as it is read**, closing the gap in decision 8. Rejected
for this phase because a losing layer is legitimately partial, so the completeness
check cannot run on it; the value check would therefore have to be split from the
completeness check and applied per key, which puts the schema inside the fold and
costs its totality. Worth revisiting when a second setting exists and the cost is
measurable rather than argued.

**Refusing rather than folding when two layers disagree.** Would make every
override an error, which is the opposite of what layering is for.

**Origins as an enumeration** rather than free text. Rejected: Phase 027 will
have several file sources whose useful identity is their path, and an enumeration
would force each into a category name less informative than the path itself.

## Risks and Trade-offs

The characteristic failure mode is the totality in decision 6 being read as
permission for the fold to accept anything, and the gap in decision 8 widening to
match. It is a comfortable failure: each new source that skips validation makes
the system slightly more tolerant of a broken document, and no single step looks
unreasonable.

The observable signal is an operator report of a setting that "did nothing" whose
cause turns out to be a value that was never read — or a phase adding a source
that returns a layer built from values it has already interpreted, which would
mean the coercion rules had escaped the domain after all.

A second risk is specific to flat keys. If a later phase introduces a setting
that genuinely is a nested structure — a per-symbol override table is the obvious
candidate around Phases 049-064 — flat dotted keys will express it awkwardly, and
the pressure will be to add deep merge rather than to reconsider whether that
setting should be a document of its own. This record does not resolve that;
it names it, so the argument happens deliberately.

## References

- [ADR-0027](0027-configuration-is-a-frozen-dataclass-validated-at-the-boundary.md)
  — the model this fold feeds, and where refusal lives.
- [`../CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md) — the precedence
  rules as an operator reads them.
- [`../engineering/ENGINEERING_CONTRACT.md`](../engineering/ENGINEERING_CONTRACT.md)
  — invariant 3, which requires the fold's output not to depend on iteration
  order.
- [`../research/phase_007_sources.md`](../research/phase_007_sources.md) —
  entries S-05 and S-06 on TOML keys.

## Supersedes

None.

## Superseded By

None.
