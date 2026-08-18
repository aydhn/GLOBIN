# ADR-0081: Configuration explains itself through two fingerprints and one manifest

## Status

Accepted — Phase 030.

**Date:** 2026-08-18

## Context

Since Phase 007 a resolved setting has carried the origin of the layer that won it.
[`CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md) says why: "the question an
operator asks when configuration surprises them is never *what is the value* — they
can see that — but *which file set it*." Phase 027 added four documents and the
environment underneath that model, so by Phase 029 there were five ordered sources
and every winning value knew which of them supplied it.

Nothing could ask. The data existed; the projection did not. `config.valid`
reported one sentence, `config_fingerprint` reported one digest, and an operator
whose configuration surprised them had no way to get the answer the model was
already holding.

Three further pressures arrived with it.

**A fingerprint that ignores origins cannot answer a question about origins.**
`config_fingerprint` deliberately excludes them, and its docstring argues the case:
"the same values loaded from a different path are the same configuration, and
folding the origin in would make a fingerprint change when somebody moved a file."
That is right for "were these two runs configured the same way" and useless for "did
anything about how this resolved move" — and the second question is the one that
catches a value which quietly began arriving from an environment variable instead of
a committed document.

**A redacted display cannot be compared.** Redaction replaces a value with a
constant, so two redacted displays are always equal. A drift report built on
displays would report "unchanged" for precisely the fields it could not see.

**A document is the one part of GLOBIN an operator writes by hand and keeps across
upgrades**, and nothing in it said which contract it was written for.

## Decision

**Two fingerprints, held apart on purpose.**

- `config_fingerprint` stays exactly as it is: values only, origins excluded. It
  answers *were these two runs configured the same way*.
- `evidence_fingerprint` includes each field's origin and priority. It answers *did
  anything about how this resolved move*.

They disagree exactly where they should, and that disagreement is the reason both
exist. A caller that wants one cannot accidentally get the other's answer.

**Every field carries a digest as well as a display.** The display is redacted by
key name, reusing `globin.domain.observability.redact` so that a configuration dump
and a log record cannot hide different things. The digest is domain-separated,
folds the key in, and uses `repr` rather than `str` so that `"1"` and `1` are
distinguishable. Change detection reads digests; nothing reads a value.

The digest is weakest against a low-entropy value and strongest against a
high-entropy one, **which is the direction that matters**: a credential is
unguessable, and a `true` was never a secret. `SECURITY_BASELINE.md` says no secret
reaches configuration at all, so this protects a case that should not occur.

**`config_schema_version` is a reserved document key, not a setting.** It has to be:
`as_config` refuses every key outside `known_keys()`, so a document declaring its own
version through an ordinary setting would be rejected by the mechanism the version
exists to protect. It is extracted before the document is flattened — the same
treatment `reserved_variables()` gives `GLOBIN_PROFILE`. Omitting it is not an error;
declaring an unsupported one fails closed **in both directions**, because a version
from the future has keys this GLOBIN does not understand and a version from the past
would require a silent upgrade, which `CONFIGURATION_POLICY.md` refuses.

**Precedence gains a layer at each end, and the whole order follows one rule:
narrowness.** A committed document applies to every invocation; an explicit document
to every invocation that names it; an environment variable to a shell session; a
`--set` flag to exactly one run. The narrowest act wins, because it is the one
somebody performed most deliberately and the one whose result they are most likely
to be watching.

- `--config PATH` sits above the four computed documents and below the environment.
  It is resolved to an absolute path, so the working directory cannot change what is
  read, and **its absence is fatal** where the four computed ones are optional: an
  absent `config/local/globin.toml` means the operator wrote none, while an absent
  `--config` means they named one that is not there.
- `--set KEY=VALUE` is the strongest source. Keys are validated against
  `known_keys()` — the typed field registry, derived from the dataclasses — so there
  is no arbitrary path to accept, and a credential-shaped key is refused before its
  value is read. **Only keys an operator typed enter the layer**, which is what stops
  an omitted flag from overwriting a lower source.

**One manifest, six sections.** `.globin/config/config-manifest.json` carries `load`,
`provenance`, `effective`, `fingerprint`, `validation` and `drift` as sections of one
document with one digest. Six files would make it possible to hold five that agree
and one that does not, and `QUALITY_GATES.md` records that a second artefact path
broke a CI job in Phase 015.

**The drift baseline is machine state, not repository evidence.** The manifest goes
under `.globin/`, which is Git-ignored and regenerable; the snapshot a later run
compares against goes in the user-local `state` area through the atomic store. That
is [`CONFIGURATION_LAYOUT.md`](../engineering/CONFIGURATION_LAYOUT.md)'s three-trees
table applied: a fresh clone must not inherit a baseline from somebody else's
checkout. **No baseline is `unmeasured` rather than clean**, which is the treatment
`tools/quality/drift` gives an unrecorded baseline for the same reason.

**What this does not cover.** No hot reload, no migration engine, no writing of any
document — `tomllib` cannot write, which is the property that makes an operator's
comments safe rather than a rule somebody keeps.

## Consequences

**What this costs.**

- Two digests over one configuration, computed on every reporting invocation, plus a
  per-field digest. On thirty-seven settings that is negligible; it is stated because
  it is per-field rather than per-run and will grow with the register.
- A second digest to explain. Anybody reading a manifest now has to know which
  fingerprint answers which question, and the documentation carries that rather than
  the field names implying it.
- `TomlConfigurationSource` now stats a file before opening it and pops a key before
  flattening. Two more things happen inside a class whose module docstring says it
  does two things and deliberately not a third — mitigated by neither of them
  interpreting a value: the version is handed to the domain, and the size check is a
  domain helper.
- `TOMLDecodeError` had to be handled at the command line. It is a `ValueError`, so
  neither the pipeline's `(GlobinError, OSError)` clause nor `main`'s saw it; before
  `--config` existed, every document the chain read was a committed one and the path
  was unreachable rather than handled. The exception is still not wrapped — a caller
  below the command line sees `tomllib`'s own type, with its line and column — but
  the CLI now turns it into exit code 14 instead of a traceback.

**What is now prohibited that a contributor might reasonably want.**

- Collapsing the two fingerprints. Whichever survived would silently stop answering
  one of the two questions.
- Comparing drift on displays. It reads as simpler and is wrong for exactly the
  fields that matter most.
- Six evidence documents, or a second artefact directory.
- A `--set` accepting an arbitrary dotted path. The registry is the gate.

**What enforcement exists.** `tests/unit/test_config_evidence.py` asserts the
fingerprints disagree on a source move and agree on values;
`tests/integration/test_config_evidence_end_to_end.py` asserts the six-layer order,
that the same explicit inputs from two working directories produce the same
fingerprints, and that a credential-shaped fixture value appears in no record, no
snapshot, no drift report and no refusal.

## Alternatives Considered

**One fingerprint that includes origins.** Simpler, and it destroys the property
`config_fingerprint` was built for: moving a file would report a change, which is the
false positive that trains people to ignore a comparison.

**One fingerprint that excludes them, with drift computed from the manifest.**
Also simpler, and it cannot see a re-origination at all — the case where a value
began arriving from somewhere less reviewable while staying the same.

**Store raw values in the snapshot so drift can compare them directly.** Refused.
The snapshot is written to disk and is the document most likely to be copied
somewhere else; the least it can hold while still answering "did this change" is the
least it should hold.

**Store no digest for a credential-shaped key, and report only "present".** Safer in
the abstract, and it loses the ability to say whether such a field changed — which is
the one question worth asking about a field nobody may look at. The digest was chosen
because its weakness is confined to values that are not secrets.

**Make `config_schema_version` an ordinary setting.** Refused: `as_config` would
reject it, and exempting it there would put a special case inside the refusal that
protects every other key.

**Put `--set` above the four documents but below the environment.** Considered, on
the argument that a shell variable is "more deliberate" because it was exported
on purpose. Rejected: a variable outlives the command, a flag does not, and the rule
the rest of the order already follows is narrowness rather than intent.

## Risks and Trade-offs

**The characteristic failure mode is two fingerprints that nobody distinguishes.**
If operators treat them as one number with a spare, the evidence digest becomes noise
— it moves on file moves, which is exactly what the semantic one was built to avoid —
and people stop reading both. **The observable signal is a bug report, or a runbook,
that quotes `evidence_fingerprint` while asking a question only `config_fingerprint`
answers.** The remedy is documentation rather than code, which is why
`CONFIGURATION_EVIDENCE.md` states the split before it states the mechanism.

**The second risk is the field digest against a low-entropy secret.** If a future
phase put something short and sensitive into configuration, the digest would be
brute-forceable where the display was not. Two rules stand between that and reality —
`SECURITY_BASELINE.md`, and the credential-shaped-name refusal — and both are rules
rather than mechanisms. A phase that ever needs a genuinely sensitive configuration
value should revisit this rather than assume the digest covers it.

**A third: drift against a baseline in a deletable tree.** Every area of the
user-local tree is documented safe to delete, so a routine cleanup silently returns
drift to `unmeasured`. That is the correct verdict rather than a wrong one, and it
means "no drift reported" is never by itself evidence that nothing moved — which is
why `unmeasured` is a distinct state and not a clean one.

**Confidence.** High on the precedence extension and the refusals, which are
mechanical and directly tested. Moderate on the two-fingerprint split, whose value
depends on operators asking the second question; if they never do, the honest later
move is to delete the evidence digest rather than keep it for symmetry.

## References

- [ADR-0079](0079-phase-030-widens-to-deliver-the-configuration-evidence-surface.md)
  — the amendment this half belongs to.
- [ADR-0071](0071-configuration-precedence-is-declared-and-an-environment-variable-is-a-derived-name.md)
  — the precedence extended at both ends.
- [ADR-0069](0069-configuration-is-derived-rather-than-searched-and-a-profile-names-a-document.md)
  — the layout, and the working-directory limitation this reports on.
- [`docs/CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md) — the register and the
  refusal table.
- [`docs/engineering/CONFIGURATION_EVIDENCE.md`](../engineering/CONFIGURATION_EVIDENCE.md)
  — provenance, the two digests, drift and the manifest.
- [`docs/security/SECURITY_BASELINE.md`](../security/SECURITY_BASELINE.md) — why no
  secret reaches configuration.

## Supersedes

None.

## Superseded By

None.
