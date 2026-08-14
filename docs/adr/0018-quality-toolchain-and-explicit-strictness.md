# ADR-0018 — The quality toolchain is pinned, and strictness is written out flag by flag

## Status

Accepted — Phase 004.

**Date:** 2026-08-14

## Context

Phase 001 chose pytest, Coverage.py, Ruff and mypy and configured them
minimally. Phase 004 had to decide whether those choices stand, and how strict
the configuration should be, now that the gates become mandatory rather than
advisory.

Two specific problems surfaced while doing it.

**Aliases hide their contents.** `mypy --strict` is not a setting; it is a name
for a set of settings that mypy owns. On the version this was written against it
expands to thirteen flags, and that membership has changed between releases.
Under the alias, upgrading mypy can add or remove a check with no diff, no
review and no test failure — the configuration keeps saying `strict = true`
while meaning something different.

**A configuration can be inert and look correct.** The repository had carried
`--strict-markers` in pytest's `addopts` since Phase 001, and believed
unregistered markers were rejected. They were not: in that form pytest emits a
`PytestUnknownMarkWarning` and the run passes. Only the `strict_markers` ini
option is enforced at collection. Nothing revealed this until a test was written
that used an unregistered marker and asserted the run failed.

That second discovery is the reason this record exists in the form it does. A
setting that is present, spelled correctly, and doing nothing is not a
hypothetical.

## Decision

**1. The toolchain stands**: pytest for tests, Coverage.py for measurement, Ruff
for linting and formatting, mypy for types, pre-commit for the local hook gate.
All are free and open source, as [ADR-0003](0003-zero-budget-open-source-dependency-policy.md)
requires.

**2. mypy strictness is enumerated.** Every flag `--strict` implies is written
out in `pyproject.toml`, read from `mypy --help` on the version in use rather
than from memory. `strict = true` is prohibited, and a contract test asserts it
has not returned.

**3. pytest strictness is declared as ini options**, not as flags in `addopts`.
`strict_markers`, `strict_config` and `xfail_strict` are set directly, and a
test proves an unregistered marker is genuinely rejected by building a throwaway
project from this repository's own settings.

**4. Coverage is branch-aware with a floor.** Measured over `globin` and
`tools`, gated repository-wide. Exclusions use `exclude_also`, which adds to
Coverage.py's defaults, rather than `exclude_lines`, which replaces them.

**5. Ruff rules are selected by family against a stated priority order** —
correctness, import hygiene, unused code, bug patterns, modern Python,
maintainability — and the families deliberately excluded are recorded with
reasons.

**6. Tool versions are pinned** to a single version across the local
environment, the pre-commit hook and CI, so all three produce the same verdict.

This decision does **not** cover docstring conventions, naming conventions, or
the docstring linting that enforces them. Those remain Phase 013.

## Consequences

- A mypy upgrade cannot silently change what the type contract means. It also
  cannot silently improve it: a flag added to `--strict` upstream will not
  arrive here until someone adds it, which is the intended trade.
- `pyproject.toml` is longer and more repetitive than `strict = true`. Thirteen
  lines is the price of the configuration meaning the same thing next year.
- The marker guard now genuinely works, which it did not for three phases.
- `disallow_any_explicit` is not enabled. The contract tests parse TOML, whose
  return type is honestly `dict[str, Any]`; banning the annotation would not
  remove the `Any`, it would replace an accurate label with a cast asserting
  something untrue.
- Four standing lint exemptions exist, each with a written justification in
  [`STATIC_ANALYSIS.md`](../engineering/STATIC_ANALYSIS.md). A fifth added
  without one should be treated as a defect.
- Pinning a single Ruff version means an upgrade is a deliberate change that may
  surface new findings all at once, rather than a trickle nobody attributes.

## Alternatives Considered

**Keep `strict = true` and pin the mypy version instead.** Rejected as solving
the symptom. A pinned version still has to be upgraded eventually, and at that
point the change in meaning arrives all at once and invisibly. Writing the flags
out means the upgrade shows exactly what it altered.

**Adopt pytest's umbrella `strict` ini option**, which enables every strictness
setting at once. Rejected for the same reason as `mypy --strict`: it is an alias
whose membership pytest owns and may extend. The individual options are three
lines and cannot change meaning underneath the project.

**Enable a much larger Ruff rule set.** Rejected. Enabling hundreds of rules
because they exist produces findings nobody reads, and a team that learns to
ignore linter output has a worse linter than one with fewer rules it trusts.

**No coverage threshold at all**, as `TESTING_STRATEGY.md` originally argued.
Rejected, but only partly: the original reasoning about thresholds-as-targets is
correct and is preserved. What it missed is that a floor set *below* current
coverage catches a module quietly losing its tests, which nothing else does.

**Let each of local, hook and CI use its own tool versions.** Rejected. Two
versions of a linter is two verdicts, and the resulting "passes locally, fails
in CI with nothing changed" is the most expensive kind of build failure.

## Risks and Trade-offs

The characteristic failure of enumerated flags is falling behind. mypy will add
checks to `--strict` that GLOBIN does not adopt, and the configuration will
slowly become weaker than the alias it replaced while appearing rigorous. The
observable signal is the flag list going unchanged across several mypy major
versions. Phase 013 should re-read `mypy --help` and diff it against this
configuration rather than assuming it is current.

Pinning exact versions carries the mirror risk: the pins are a reproducibility
measure taken in the absence of a real dependency-management strategy, and they
are not one. Phases 018 and 020 own interpreter pinning and lockfiles
respectively, and are expected to replace this arrangement rather than inherit
it. Treating four `==` constraints as a solved dependency story would be the
mistake.

The coverage floor's failure mode is complacency: 95 % is high enough to look
reassuring and low enough that a genuinely undertested new module can hide
inside it. Coverage says what executed, never what was checked.

## References

- [`../engineering/STATIC_ANALYSIS.md`](../engineering/STATIC_ANALYSIS.md) — the
  rule families, the exception procedure and the standing exemptions.
- [`../engineering/QUALITY_GATES.md`](../engineering/QUALITY_GATES.md) — where
  the gates run and what happens when one fails.
- [`../research/phase_004_sources.md`](../research/phase_004_sources.md) —
  entries S-01 to S-06 for the tool documentation this rests on.
- [ADR-0003](0003-zero-budget-open-source-dependency-policy.md) — the
  free-and-open constraint the toolchain satisfies.

## Supersedes

None.

## Superseded By

None.
