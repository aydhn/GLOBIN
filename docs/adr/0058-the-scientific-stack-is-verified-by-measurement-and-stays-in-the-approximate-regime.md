# ADR-0058 — The scientific stack's verdict is recomputed from measurement, and the stack stays in the approximate regime

## Status

Accepted — Phase 022.

**Date:** 2026-08-16

## Context

[ADR-0055](0055-the-first-runtime-dependencies-are-introduced-and-globin-becomes-installed.md)
declared `numpy` and `pandas`, wrote a six-question review for each, and pinned
both in `pylock.toml`. It was explicit that it made "no claim about numerical
correctness" and left that to this phase. `ROADMAP.md` gives Phase 022 the same
instruction in the imperative: *confirming correctness rather than assuming it*.

Two earlier records left a specific hole behind them.
[ADR-0052](0052-wheel-availability-is-a-recorded-survey-whose-verdict-is-recomputed.md)
established that a published wheel filename is a claim about **availability**,
not about behaviour, and
[`../research/phase_018_sources.md`](../research/phase_018_sources.md) files
"whether each wheel, once installed, actually works on this host" against Phase
022 by name. So the survey proved a wheel exists; nothing has yet proved the
thing inside it computes.

The obvious implementation is the wrong one. A check that concludes "the stack is
installed" because `import numpy` did not raise is assumption wearing
verification's clothes: it proves a file was found, which the lock already
guaranteed, and says nothing about whether `float64` on this host is the type
every later phase's arithmetic will assume it is.

There is also a boundary that has to be settled before the first import, not
after. [`../PRECISION_POLICY.md`](../PRECISION_POLICY.md) rule 1 is a one-way
door: a `float` may never be the last transformation before a venue or a ledger,
and may never decide a refusal. The same document defers the numeric type
indicators and models use to Phases 113-128, and cross-host bit-identity to Phase
158. Adopting `numpy` into the domain here would settle a question two bands away
by accident, which is exactly what `docs/CONFIGURATION_POLICY.md` warns about
regarding `config/`.

## Decision

**The stack's verdict is recomputed from measurement, in the shape the
`wheels`, `lock`, `drift` and `runtime` gates already use.**
[`../engineering/stack-contract.toml`](../engineering/stack-contract.toml)
declares what must be true; `python -m tools.quality stack` measures this host,
recomputes every verdict from the evidence beside it, and writes
`.globin/stack/stack-manifest.json`. Nothing in the declaration is believed
because it is written down.

**It reaches no network.** No index is consulted, no resolver runs and `pip` is
never invoked. The question is entirely about what is installed here, now.

### What is measured

**Four-way version agreement.** The installed distribution's metadata, the pin in
`pylock.toml`, the bound in `pyproject.toml` and the declaration in
`stack-contract.toml` must name one version each and agree. Three registers
already exist and a fourth is being added, so the failure worth catching is
drift between them rather than any one of them being wrong.

**Provenance.** The installed `.dist-info` is checked against the tags the pinned
interpreter actually accepts, so a wheel built for a different ABI — a
free-threaded build, another minor line, another architecture — is caught as a
wrong artefact rather than as a mysterious crash later.

**Identity.** The imported module must resolve inside the project environment.
A `numpy` shadowed by a stray directory earlier on the path is a different
library from the one the lock pinned, and the digest in `pylock.toml` says
nothing about which one gets imported.

### The behaviour probes

Seven, each with a stable identifier that appears in the evidence. Each was run
on this host before being written down, and each exists because a specific GLOBIN
assumption rests on it.

| Probe | What it establishes |
|---|---|
| `numpy.float64_is_binary64` | 52 stored mantissa bits, `eps` of exactly `2**-52`, 64-bit, 8 bytes — the IEEE-754 binary64 the approximate regime is defined in terms of |
| `numpy.nan_and_infinity_propagate` | Division producing `inf` and `nan` propagates rather than raising or substituting, and `nan != nan` holds |
| `numpy.integer_overflow_wraps_observably` | A 64-bit overflow wraps **and emits a `RuntimeWarning`**, so it is detectable rather than silent |
| `pandas.float64_round_trip_is_bit_exact` | A `float64` array through a DataFrame and back is bit-identical, including `-0.0` and subnormals |
| `pandas.missing_value_survives_a_round_trip` | `NaN` stays `NaN` and does not become `0.0`, and the column stays `float64` |
| `pandas.utc_timestamp_round_trip_preserves_the_instant` | A UTC-aware timestamp keeps its instant and its awareness, satisfying `TIME_POLICY.md`'s UTC-only rule |
| `pandas.copy_on_write_is_active` | Mutating a derived Series does not write through to its parent |

**The probes assert on documented numeric semantics and read no deprecated
option.** pandas 3.0 removed the ability to disable copy-on-write and deprecated
`mode.copy_on_write`, which emits a `Pandas4Warning` when read.
`pandas.copy_on_write_is_active` therefore observes the *behaviour* — a parent
frame is unchanged after its child is mutated — rather than the flag. A probe
that read the flag would fail on pandas 4 for a reason unrelated to correctness.

### What this does not decide

- **The numeric type indicators and models use** — Phases 113-128.
- **Bit-identical reproducibility of a float computation across hosts** —
  Phase 158. This gate measures one host and claims nothing about another.
- **GPU acceleration** — Phases 023-024. **Native TA-Lib** — Phase 025.
- **Any adoption.** Verifying is not importing.

### Nothing under `src/globin` imports `numpy` or `pandas`

`tests/architecture/test_stack_discipline.py` walks the real source tree and
fails on either import, with its own failing cases in both directions — the
pattern `test_clock_discipline.py` and `test_precision_discipline.py` already
use. It is a tripwire from its first commit, and it is what keeps
`PRECISION_POLICY.md`'s one-way door shut while the door is still cheap to hold.

The first legitimate import arrives with the phase that owns a use for it. When
that happens the tripwire is edited deliberately, in that phase's diff, rather
than eroded by somebody reaching for the convenient thing.

### `numpy` and `pandas` leave the wheel survey

ADR-0052 established that a survey entry naming a delivered phase is "an adoption
wearing a survey's clothes", and `tools/quality/wheels/gate.py` enforces it. Both
entries are therefore removed from
[`../engineering/wheel-survey.toml`](../engineering/wheel-survey.toml) and
`DELIVERED_PHASE` rises from `18` to `22`. The survey keeps answering its own
question — does a wheel exist for a library a *future* phase schedules — and this
gate takes over the one that is now answerable by running the code.

## Consequences

There is a fourth register naming a version, and it can disagree with the other
three. That is the cost of declaring what a gate checks; the gate's first job is
to compare all four, so a disagreement fails loudly rather than being discovered
by a wrong number six phases later.

`python -m tools.quality stack` imports `numpy` and `pandas`, so it is the first
quality command whose runtime is measured in seconds rather than milliseconds. It
is a standalone command rather than a step in `full`, exactly as `runtime`,
`wheels`, `drift` and `lock` are, and its contract test runs inside the ordinary
suite so a commit is still gated.

A probe that fails is not necessarily a broken library. It may be a broken host,
a shadowed import or a wheel from the wrong ABI, and the manifest names which of
those it found — but the operator's first move is to rebuild `.venv` from the
lock rather than to distrust upstream.

The architecture tripwire will one day block a legitimate change, and whoever
hits it must read this record to learn that blocking them is the intent.

## Alternatives Considered

**Check that `import numpy` succeeds, and stop.** The cheapest thing that could
be called verification. Rejected because the lock already proves the files are
present; an import check adds no information and would let the phase claim
"verified" for work nobody did.

**Run upstream's own test suites.** `numpy.test()` and the pandas equivalent are
the most thorough option available. Rejected for three reasons: they take minutes
and need `pytest` inside the measured environment, they answer "is this build
correct in general" rather than "does this host satisfy GLOBIN's assumptions",
and a red upstream test GLOBIN does not depend on would block a commit for
something GLOBIN never uses.

**Assert bit-identical results for a fixed computation, stored as a golden
digest.** Attractive because it is a single strong check. Rejected because
`PRECISION_POLICY.md` gives cross-host bit-identity to Phase 158, and a golden
digest would silently make this phase decide it — while failing on any host with
a different BLAS, which is a portability claim nobody has evidence for.

**Import `numpy` into `globin.domain` and build the first typed array wrapper.**
It would have made the phase feel like adoption rather than verification.
Rejected because it settles Phases 113-128's question, and because
`PRECISION_POLICY.md`'s one-way door is far cheaper to hold before the first
import than after the tenth.

**Leave `numpy` and `pandas` in the wheel survey.** `DELIVERED_PHASE` is
documented as a floor rather than a mirror, so nothing would have failed.
Rejected because the survey would then describe a phase that has shipped, which
is the precise condition ADR-0052 wrote its check to catch — passing on a
technicality is not the same as being true.

## Risks and Trade-offs

**The characteristic failure mode is probe rot** — a probe that keeps passing
while meaning nothing, because the behaviour it asserts became untestable or the
assertion was weakened to survive an upgrade. The observable signal is a probe
whose body no longer references the value it is named after, or one relaxed in
the same commit that raised a version.

**The second is that the probes are mistaken for a correctness proof.** Seven
behaviours are not the whole of two large libraries. What this gate establishes
is that *the specific assumptions GLOBIN has written down* hold here. The signal
that this has been forgotten is a later phase citing the stack gate as grounds
for not testing its own numerics.

**The third is the four-way comparison becoming a chore.** Four registers must
agree, and a version bump touches all four. The signal is somebody adding a
`# noqa`-shaped exemption, or the gate being run less often than the lock is
regenerated.

Confidence is high: every probe was executed on the target host before it was
recorded, and each maps to a written GLOBIN assumption rather than to a general
notion of library health.

## References

- [ADR-0045](0045-a-platform-capability-is-a-recorded-state-never-a-pass.md) — why an unmeasured claim is never a pass
- [ADR-0052](0052-wheel-availability-is-a-recorded-survey-whose-verdict-is-recomputed.md) — availability is not behaviour, and the delivered-phase rule
- [ADR-0055](0055-the-first-runtime-dependencies-are-introduced-and-globin-becomes-installed.md) — the declaration this verifies
- [ADR-0057](0057-phase-022-widens-to-deliver-the-runtime-filesystem-and-lifecycle.md) — the amendment that put this phase's second half beside this one
- [`../PRECISION_POLICY.md`](../PRECISION_POLICY.md) — the one-way door, and the deferrals to 113-128 and 158
- [`../TIME_POLICY.md`](../TIME_POLICY.md) — the UTC-only rule the timestamp probe checks
- [`../engineering/SCIENTIFIC_STACK.md`](../engineering/SCIENTIFIC_STACK.md) — how to run this and how to read it
- [`../research/phase_022_sources.md`](../research/phase_022_sources.md) — the upstream documentation each probe was written from

## Supersedes

None.

## Superseded By

None.
