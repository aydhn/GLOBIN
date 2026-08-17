# ADR-0071 — Configuration precedence is one declared order, and an environment variable is a derived name

## Status

Accepted — Phase 027.

**Date:** 2026-08-17

## Context

Phase 007 built a configuration model whose fold is total and whose refusal is
single-sited. Phase 026 gave configuration a place to live — four documents computed
from a layout and a profile — and deliberately returned them as a *mapping* so that no
reader could mistake a listing order for a precedence. Neither phase decided which
sources are consulted, in what order, or whether a missing document is fatal.

Three things therefore did not work, and one of them was a hole rather than a gap:

- Nothing read the environment, so an operator could not change a setting without
  editing a committed file.
- Nothing selected a profile, so `DEFAULT_PROFILE` was what every run used and what
  every health snapshot recorded.
- `bootstrap check` resolved **no sources at all**, so preflight validated the declared
  defaults rather than the configuration the process would actually run on. A document
  or variable that `as_config` refuses passed the gate and failed at start-up, which is
  the exact inversion of what a fail-closed gate is for.

## Decision

**Precedence is declared in two functions and assembled in one.**

- `config_layout.precedence()` returns the four document roles weakest first: base,
  profile, local base, local profile. It encodes two rules — specific beats general,
  and uncommitted beats committed — and it is the only place that order exists.
  `documents_for()` still returns a mapping, because the *set* of candidates and the
  *order* they fold in are different facts.
- `config_layout.profile_from()` orders a launcher argument above `GLOBIN_PROFILE`
  above the declared default. The more deliberate act wins.
- `composition.build_config_sources()` puts the environment **above every document**,
  for the same reason: a variable is set for one invocation, a committed document for
  every one.

**An environment variable name is derived from the setting key, never declared beside
it.** `telemetry.enabled` becomes `GLOBIN_TELEMETRY_ENABLED`. Derivation costs the
possibility of two keys colliding on one name, and the answer is a contract test
asserting the map is injective over `known_keys()` rather than a hope.

**An unrecognised `GLOBIN_` variable is refused, and a credential-shaped one is refused
first.** The prefix is what makes a typo *detectable*; without a namespace the choice
would be between ignoring typos and refusing to start because of somebody else's
`PATH`. `GLOBIN_PROFILE` is exempt through a named `reserved_variables()` list, because
it decides which documents are read and so cannot be one of the settings they contain.

**A missing document is answered by a wrapper, not a flag.** `OptionalDocumentSource`
turns absence into an empty layer; a file that exists and cannot be read, a malformed
document and an unflattenable key all propagate. The wrapper sits at the composition
root, so which documents are required is visible where the chain is assembled.

**Preflight resolves what a run resolves.** `build_bootstrap` defaults to the real
chain.

## Consequences

**Not one binder was added to read the environment.** Phase 026 wrote `_flag` and
`_bounded` to accept strings, with docstrings naming this phase as the reason, so the
validation rule stayed in one place exactly as predicted. The environment source
parses nothing and validates nothing.

**A misspelled profile is refused, never defaulted.** A selection that quietly became
the safe profile would be the reassuring half of a bad mechanism; the same mistake in
the other direction quietly becomes `live`, and refusing both is how one rule covers
both. The default is reached only when nobody asked.

**The health snapshot's `config_fingerprint` now describes the run.** It was computed
over the defaults layer alone, because that was the only layer there was; with real
sources folded in, a second resolution could have differed from the one the process was
using. `ConfigurationResolution.resolved()` exists so both come from one fold.

**A latent defect surfaced and was fixed.** `_bounded` screened strings with
`str.isdigit`, which is true for characters `int` refuses — a superscript two among
them — so the pair raised `ValueError` on input it had just declared acceptable, escaping
the error taxonomy entirely. Unreachable while every string came from a TOML document;
live the moment environment variables arrived. A property test over generated text
found it, and both sites now use `str.isdecimal`.

**A diagnostics command can now fail for a configuration reason**, so the CLI maps
`ConfigurationError` to exit `14` rather than reporting "no diagnostic could be
produced". Code `24` stays free.

## Alternatives Considered

**A declared table of variable names.** Readable, and a second place to add a setting
and therefore a place to forget one. Refused: the collision risk derivation introduces
is checkable, and a stale table is not.

**Ignore an unrecognised `GLOBIN_` variable.** Tolerant of a stray variable from
another tool, and silent about the typo that disables a setting an operator believes
they set — the failure the whole model exists to prevent.

**A `missing_is_empty` flag on `TomlConfigurationSource`.** Fewer types, and it puts
the decision inside the reader where a caller assembling a chain cannot see which of
its documents are required. Which documents are required is precisely what this phase
was asked to make explicit.

**Read the environment in the domain layer.** Impossible: `os` is I/O-capable and the
domain may import none of it. The environment is handed in, which is the treatment
`resolve_root` already gets.

## Risks and Trade-offs

**A stricter preflight can refuse a host that used to pass.** That is the point, and it
means an installation carrying an invalid document learns about it at the gate rather
than at start-up.

**Refusing unrecognised `GLOBIN_` variables will eventually annoy somebody** who
exports one for another purpose. The prefix is GLOBIN's namespace and the alternative
is ignoring typos; a future non-setting variable is added to `reserved_variables()`.

**The environment outranking every document is a choice, not a law.** A deployment that
wanted a committed document to be authoritative cannot express that. Nothing yet needs
it, and inverting it later is one function.

## References

- [`../CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md) — the register and the
  precedence rules.
- [`../engineering/CONFIGURATION_LAYOUT.md`](../engineering/CONFIGURATION_LAYOUT.md) —
  where documents live.
- [ADR-0027](0027-configuration-is-a-frozen-dataclass-validated-at-the-boundary.md) — the model
  this builds on.
- [ADR-0069](0069-configuration-is-derived-rather-than-searched-and-a-profile-names-a-document.md)
  — the layout, and the deferral this closes.
- [ADR-0070](0070-phase-027-widens-to-deliver-the-loopback-diagnostics-surface.md) — the
  amendment that carried this phase.

## Supersedes

Nothing.

## Superseded By

Nothing.
