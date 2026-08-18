# Configuration Evidence

How a resolved configuration explains itself: which source won each key, what the
whole thing digests to, and what changed since the last run.

[`../CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md) owns the *model* — what a
setting is, how layers fold, which values are refused.
[`CONFIGURATION_LAYOUT.md`](CONFIGURATION_LAYOUT.md) owns the *layout*. This owns
what a resolution can be asked **about itself**. The split is
[ADR-0081](../adr/0081-configuration-explains-itself-through-two-fingerprints-and-one-manifest.md)'s.

---

## The precedence, in full

Six sources, folded weakest first. The last layer that mentions a key wins.

| # | Source | Origin | Absent means |
|---|---|---|---|
| 0 | Typed code defaults | `defaults` | Cannot be absent |
| 1 | `config/globin.toml` | its path | The operator wrote none |
| 2 | `config/profiles/<profile>.toml` | its path | The operator wrote none |
| 3 | `config/local/globin.toml` | its path | The operator wrote none |
| 4 | `config/local/profiles/<profile>.toml` | its path | The operator wrote none |
| 5 | `--config PATH` | its absolute path | **Refused.** They named one that is not there |
| 6 | `GLOBIN_*` environment variables | `environment` | A process always has an environment |
| 7 | `--set KEY=VALUE` | `command line` | Nothing was overridden |

**The whole order follows one rule: narrowness.** A committed document applies to
every invocation; an explicit document to every invocation that names it; a variable
to a shell session; a flag to exactly one run. The narrowest act wins, because it is
the one somebody performed most deliberately and the one whose result they are most
likely to be watching.

Phases 026 and 027 established layers 0-4 and 6. Phase 030 added 5 and 7, at the two
ends, following the same rule rather than a new judgement.

### The two Phase 030 added

**`--config PATH` is a source selection, not a field.** It says which document to
read, never what a setting is, so it never appears in the provenance as a value and
"why is this setting what it is" still names the document rather than the flag. It
is resolved to an absolute path before it is read, so two invocations naming one
document from different working directories are one invocation. **Its absence is
fatal**, which is the one way it differs from the four computed documents.

**`--set KEY=VALUE` is repeatable and validated against the register.** The typed
field registry is `known_keys()`, derived from the dataclasses, so there is no
arbitrary path to accept and a key that is not a setting is refused before its value
is looked at. A credential-shaped key is refused on its *name*, so the value is never
read. **Only keys an operator typed enter the layer** — a parser default reaching
this source would make the strongest layer set every setting on every run, and no
document below it could ever win.

### Windows environment names

A variable name is derived rather than declared: `logging.min_severity` becomes
`GLOBIN_LOGGING_MIN_SEVERITY`. Upper case with underscores, because Windows compares
variable names case-insensitively and a lower-case scheme would give two spellings of
one name on one host and two distinct names on another. Derivation costs the
possibility of two keys collapsing onto one variable, and the answer is not to hope:
`tests/contract/test_configuration_contract.py` asserts the map is injective over
`known_keys()`, so a colliding pair fails the suite instead of silently making one
setting unreachable.

---

## Provenance

Every key any layer mentioned carries an account.

| Field | What it holds |
|---|---|
| `key` | The dotted setting name |
| `display` | The value as it may safely be shown, redacted by key name |
| `digest` | A domain-separated digest of the real value |
| `origin` | The layer that won |
| `priority` | That layer's position in the fold; zero is weakest |
| `overridden` | How many weaker layers also set this key and were overruled |
| `known` | Whether it is a registered setting |

**The data was always there.** A resolved setting has carried its origin since Phase
007. What was missing was a projection, and that is all this is: a pure reading of
layers that were already assembled.

**It takes layers rather than a resolved configuration, and it has to.** A
`ResolvedConfig` holds only winners, so the count of what was overruled is not
recoverable from it. The alternative was to make the fold carry losers, which would
change a total function used everywhere in order to serve one report.

**An unknown key still has provenance.** Naming the document that set a key that is
not a setting is exactly what an operator needs, so it is reported rather than
dropped — and `as_config` still refuses it.

---

## Two fingerprints

| Digest | Includes | Answers |
|---|---|---|
| Semantic | Values only | *Were these two runs configured the same way?* |
| Evidence | Values as digests, plus origins and priorities | *Did anything about how this resolved move?* |

**They disagree exactly where they should, and that is why both exist.** A value that
began arriving from an environment variable instead of a committed document is a
change worth seeing even though the value is identical; the semantic digest is
deliberately blind to it, because folding the origin in would make a fingerprint
change when somebody moved a file — the false positive that trains people to ignore a
comparison.

A caller that wants "same configuration" asks the first. A caller that wants "same
resolution" asks the second. Neither can be used to answer the other's question by
accident.

**Both are safe to publish.** The semantic digest redacts before folding; the
evidence digest folds field digests rather than values.

---

## Why a digest as well as a display

Redaction protects a *display*, and two redacted displays are always equal. A drift
report built on displays would report "unchanged" for precisely the fields it could
not see.

Each field therefore carries a digest of its real value, domain-separated and with
the key folded in. `repr` rather than `str`, because `"1"` and `1` are different
configurations that `str` renders identically — the hardest change to notice.

**The digest is weakest against a low-entropy value and strongest against a
high-entropy one, which is the direction that matters.** A boolean has two
candidates; a credential is unguessable. `SECURITY_BASELINE.md` says no secret
reaches configuration at all, so this protects a case that should not occur rather
than one that does. A phase that ever needs a genuinely sensitive configuration value
should revisit it rather than assume it is covered.

---

## Schema version

A document may declare which contract it was written for:

```toml
config_schema_version = 1
```

**Reserved rather than registered**, and it has to be: `as_config` refuses every key
outside `known_keys()`, so a document declaring its version through an ordinary
setting would be rejected by the mechanism the version exists to protect. It is
extracted before the document is flattened — the same treatment `reserved_variables()`
gives `GLOBIN_PROFILE`.

**Omitting it is not an error.** A document that says nothing is read as this
version, because requiring the line would break every document written before the key
existed in order to make a point about documents written after.

**An unsupported version fails closed in both directions.** From the future, because
this GLOBIN does not know what its keys mean; from the past, because silently
upgrading a document is the destructive automatic migration
`CONFIGURATION_POLICY.md` refuses. There is no migration engine. What exists is the
boundary at which one could later be written without having to guess.

---

## Drift

Two snapshots compared.

| Category | Meaning |
|---|---|
| `added` | The later run resolved a key the earlier one did not |
| `removed` | The earlier run resolved a key the later one did not |
| `changed` | The value moved |
| `reorigined` | The value did not move but the winning source did |
| `semantic_drift` | The effective configuration differs at all |
| `measured` | Whether there was a baseline to compare against |

**No baseline is `unmeasured`, not clean.** A first run has established that nothing
changed only in the sense that it has established nothing at all, and
`tools/quality/drift` treats an unrecorded baseline the same way for the same reason.
A caller that cannot tell the two apart will eventually report a machine as unchanged
because it has never been looked at.

**No value appears in a drift report, for any key.** The categories name what moved;
the digests that decided it are in the snapshot. A drift report is the document most
likely to be pasted into a message to somebody else, which is the argument for it
carrying the least.

**A credential-shaped key is compared exactly like any other**, because the
comparison reads digests rather than values.

---

## Where the two artefacts go

`CONFIGURATION_LAYOUT.md`'s three-trees table, applied.

| Artefact | Tree | Why |
|---|---|---|
| `config-manifest.json` | `.globin/config/` | Evidence about **this repository**: Git-ignored, regenerable, beside every other gate's manifest |
| `config-snapshot.json` | `%LOCALAPPDATA%\GLOBIN\state\` | State about **this machine**: a fresh clone must not inherit a baseline from somebody else's checkout |

**The comparison happens before the baseline is replaced.** Recording first would
compare a run against itself and report that nothing ever changes.

**Every area of the user-local tree is documented safe to delete**, so a routine
cleanup returns drift to `unmeasured`. That is the correct verdict rather than a
wrong one, and it means "no drift reported" is never by itself evidence that nothing
moved.

**One manifest, six sections.** The manifest carries `profile`, `provenance`,
`fingerprints`, `validation` and `drift` under one schema with one digest. Six
separate files would make it possible to hold five that agree and one that does not,
and [`QUALITY_GATES.md`](QUALITY_GATES.md) records that a second artefact path broke
a CI job in Phase 015. **No timestamp appears anywhere**: the manifest is compared
between runs, and a clock reading would make every comparison report a change.

---

## The commands

```bash
.venv\Scripts\globin.exe config validate
```

```bash
.venv\Scripts\globin.exe config explain logging.min_severity
```

```bash
.venv\Scripts\globin.exe config dump --json
```

```bash
.venv\Scripts\globin.exe config fingerprint
```

```bash
.venv\Scripts\globin.exe config evidence
```

Five verbs, and every one of them reads. `tomllib` cannot write, so GLOBIN is
structurally incapable of editing a document an operator wrote — which is the
argument `CONFIGURATION_LAYOUT.md` makes for the parser, arriving here as a property
of the command group rather than as a rule somebody keeps.

**Three of the five answer a configuration that will not bind, and two refuse.**
`explain` and `fingerprint` are diagnostics — an operator whose configuration is
broken is exactly the one who needs to know which document set the offending value —
while `dump` describes the *validated* model and would otherwise have to invent one.
`validate` refuses because refusing is the whole verb.

`config dump` reports the **bound** model rather than the resolved layer, with an
enumeration rendered as its name, so a dumped value can be pasted back into a
document unchanged.

`--json` is refused for `evidence`, which writes a file rather than a stream — the
rule `bootstrap evidence` and `diagnostics bundle` already follow.

### Windows examples

```powershell
$env:GLOBIN_LOGGING_MIN_SEVERITY = "WARNING"
.venv\Scripts\globin.exe config explain logging.min_severity
```

```powershell
.venv\Scripts\globin.exe config validate --config C:\Users\example\globin-local.toml
```

```powershell
.venv\Scripts\globin.exe doctor --set diagnostics.tracemalloc_enabled=true
```

A real credential never appears in any of these, because no such setting exists and a
credential-shaped key is refused on its name. Where an example needs a placeholder,
write `REPLACE_ME`.

---

## What this does not cover

| Question | Phase |
|---|---|
| What a setting is, how layers fold, and which values are refused | 007, delivered — [`../CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md) |
| Where documents live and what a profile is | 026, delivered — [`CONFIGURATION_LAYOUT.md`](CONFIGURATION_LAYOUT.md) |
| Collecting configuration an operator has not supplied | 291 |
| Backing configuration up and restoring it | 283 |
| Reloading configuration without restarting | Not scheduled; no phase owns it |
| What an environment is, and how production, testnet and demo differ | 035 |

**Hot reload is deliberately absent rather than deferred to a named phase.** The
effective configuration is an immutable snapshot after validation, and the API is
shaped so that a reload would produce a *new* validated snapshot rather than mutate
one. Whether that is ever wanted is a decision nobody has had to make yet.

---

## Related documents

- [`../CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md) — the settings register.
- [`CONFIGURATION_LAYOUT.md`](CONFIGURATION_LAYOUT.md) — the tree, and the profiles.
- [`../security/SECURITY_BASELINE.md`](../security/SECURITY_BASELINE.md) — why no
  secret reaches configuration.
- [`PREFLIGHT_SUITE.md`](PREFLIGHT_SUITE.md) — the other half of Phase 030.
- [ADR-0081](../adr/0081-configuration-explains-itself-through-two-fingerprints-and-one-manifest.md)
  — the decision.
