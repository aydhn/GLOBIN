# Wheel Availability

Whether the libraries this programme schedules can be installed on the interpreter
it pins, and what is recorded when one cannot.

Phase 017 declared a CPython minor line and built an environment from it. It did
that **before** anything checked that the planned stack publishes wheels for that
line — the order [`../../ROADMAP.md`](../../ROADMAP.md) stated, reversed.
[ADR-0051](../adr/0051-phase-017-absorbs-interpreter-pinning-and-the-environment-lifecycle.md)
recorded the inversion rather than glossing it, and said plainly what follows: if
the survey finds the planned stack cannot run on the pinned line, the contract
Phase 017 wrote is what changes.

This document owns that question. The machine-readable half is
[`wheel-survey.toml`](wheel-survey.toml).

---

## What this is, and what it is not

**It is a survey.** One entry per library the roadmap — or the Phase 001 source
ledger it rests on — names, recording what the index published on a stated day.

**It is not an adoption.** Nothing here is installed, nothing here enters
[`../../pyproject.toml`](../../pyproject.toml), and nothing here has been through
the six-question review in [`../DEPENDENCY_POLICY.md`](../DEPENDENCY_POLICY.md). A
library appears because the programme schedules it, not because it has been
chosen. Adoption begins at Phase 021, one written record at a time.

**It is not a resolution.** No resolver runs here, no transitive tree is claimed,
and no lock file is written. Phase 020 does that, in
[`DEPENDENCY_LOCKING.md`](DEPENDENCY_LOCKING.md) -- and it *calls this module's tag
matcher* rather than growing a second one, which is why a change to the rules here
changes what the lock gate accepts.

**It is not a measurement.** A published wheel is a claim that installation is
possible, not that the library works on this host. Whether the numerical stack
computes correctly is Phase 022, delivered —
[`SCIENTIFIC_STACK.md`](SCIENTIFIC_STACK.md); whether a GPU helps is Phases
023-024; whether TA-Lib's native library can be provisioned at all is Phase 025.

---

## How to read the survey

Two commands, and the difference between them is the network.

```bash
python -m tools.quality wheels
```

Offline. It reads [`wheel-survey.toml`](wheel-survey.toml), compares the target
against [`runtime-contract.toml`](runtime-contract.toml), and **recomputes every
recorded verdict** from the wheel filenames recorded beside it. It writes
`.globin/wheels/wheel-manifest.json` and reaches nothing.

```bash
python -m tools.quality.wheels probe
```

Reaches PyPI. Everything the check does, and then asks the index whether the
record is still true. Note the **dot**: the command table takes exactly one word,
so a subcommand goes to the sub-package directly.

Both are in the `supply` continuous-integration job, which is already the only job
that reaches outside the runner.

---

## Why the record is written by hand and the verdict is not

Every machine-readable contract in this repository carries the same banner:
**nothing writes this file**. The argument is
[`action-pins.toml`](action-pins.toml)'s — a manifest generated from the thing it
describes could only ever agree with it, which is a mirror rather than a check.

A survey has an additional problem a pin manifest does not: the verdict is a
*judgement about evidence*, and a file recording only the judgement cannot be
argued with. So the entry records the evidence too.

| Recorded | By whom | Checked how |
|---|---|---|
| Which libraries the programme schedules | A person, citing the phase | The phase must exist and must not have shipped |
| The version surveyed, and its `Requires-Python` | A person, from the index | The probe compares it against the index |
| The wheel filenames observed | A person, from the index | The probe compares them against the index |
| Whether a wheel serves the pinned interpreter | **Nobody — it is computed** | Recomputed offline from the filenames every run |

An entry claiming a wheel exists whose own filenames do not support the claim
fails without asking anything. That is what makes this a record rather than a
transcription.

---

## Deciding a wheel

A wheel filename carries three tag sets: interpreter, ABI and platform. Whether it
can be installed is decided by the **pairing** of the first two, and neither half
decides alone.

| ABI tag | What it means | Which interpreter tags it accepts |
|---|---|---|
| `none` | Binds to no Python ABI | `py3`, and any `py3N` or `cp3N` at or below the target's minor |
| `abi3` | Built against the limited API | Any `cp3N` at or below the target's minor — but **never** a free-threaded build |
| `cp314` | The default 3.14 build's ABI | `cp314` exactly, and only when the target is the default build |
| `cp314t` | The free-threaded 3.14 build's ABI | `cp314` exactly, and only when the target is free-threaded |

Three consequences are worth stating, because each is a mistake this survey would
otherwise have made.

**`py3-none-win_amd64` is a wheel.** `xgboost` and `lightgbm` publish exactly that:
platform-specific, because they carry a native library, and interpreter-agnostic,
because it is loaded through `ctypes` rather than built against a Python ABI. A
survey grepping filenames for `cp314` reports a gap in both that does not exist.

**`cp314-cp314` does not serve `3.14t`.** The free-threaded build has its own ABI.
Reading the default build's wheel as coverage would report the stack ready for a
change it is not ready for.

**`cp312-none-any` does serve 3.14, and `cp312-cp312-win_amd64` does not.** The
only difference is the ABI tag. That asymmetry cannot be expressed by matching
substrings, which is why
[`tools/quality/wheels/plan.py`](../../tools/quality/wheels/plan.py) parses tags.

The matcher is a deliberate subset of PEP 425 and says so: one implementation, one
minor line, one platform, no manylinux or macOS version ranges, no ranking of
candidates. It answers *does a wheel exist that the pinned interpreter could
install*, and nothing wider.

---

## Deciding a `Requires-Python`

Narrower still, and it refuses rather than guesses.

Supported: `>=`, `>`, `<=`, `<`. Refused by name: `==`, `!=`, `~=`, `===`,
wildcards, and any bound carrying a patch component **inside** the pinned minor
line — because a minor line alone cannot decide `<3.14.3`, and answering anyway
would be right for some patch releases and wrong for others with nothing recording
which. That is [`ENGINEERING_CONTRACT.md`](ENGINEERING_CONTRACT.md) invariant 2:
on ambiguity, refuse.

An empty `Requires-Python` is refused too. A distribution that publishes none has
made no claim, and reading silence as permission is the assumption this phase
exists to remove.

---

## A gap is recorded and owned, never assumed

The roadmap asks this phase to *record each gap rather than assuming one*. A
library whose upstream publishes no wheel is a fact about the world, and a gate
that went red over it would stay red until somebody else's release schedule
changed.

So a verdict may say there is no wheel, and the entry must then name the phase
that answers for it.

| Verdict | Meaning | `resolved_by` |
|---|---|---|
| `available` | A recorded wheel serves the target | Must be absent |
| `source-only` | No wheel; installing would build from a source distribution | **Required** |
| `absent` | Nothing usable is published | **Required** |

What fails is an **unowned** gap — recorded, then nobody's, then forgotten. It is
the bargain [`vulnerability-waivers.toml`](vulnerability-waivers.toml) strikes,
where the thing demanded is not the absence of a problem but a name against it.
Only `available` is decidable offline; telling `source-only` from `absent` means
asking the index, which is the probe's job.

---

## What is surveyed

Nineteen distributions, each against the phase whose work needs it. The versions
and filenames are in [`wheel-survey.toml`](wheel-survey.toml); this is the set and
why each is in it.

| Distribution | Phase | Why it is scheduled | Wheel shape |
|---|:---:|---|---|
| `ta-lib` | 025 | The indicator wrapper Phases 025 and 114 name | `cp314` only |
| `binance-common` | 045 | The shared runtime the SDK family requires | pure |
| `binance-sdk-spot` | 066 | Spot | pure |
| `binance-sdk-margin-trading` | 068 | Cross and isolated margin | pure |
| `binance-sdk-derivatives-trading-usds-futures` | 071 | USDS-margined futures | pure |
| `binance-sdk-derivatives-trading-coin-futures` | 073 | Coin-margined futures | pure |
| `binance-sdk-derivatives-trading-options` | 075 | Options | pure |
| `binance-sdk-derivatives-trading-portfolio-margin` | 076 | Portfolio margin | pure |
| `binance-sdk-derivatives-trading-portfolio-margin-pro` | 077 | Portfolio margin pro | pure |
| `binance-sdk-wallet` | 065 | Wallet and asset endpoints | pure |
| `binance-sdk-algo` | 089 | Algorithmic order types | pure |
| `xgboost` | 182 | Gradient boosting | `py3-none-win_amd64` |
| `lightgbm` | 182 | The alternative boosting implementation | `py3-none-win_amd64` |
| `torch` | 183 | Neural models, and what SB3 runs on | `cp314` and `cp314t` |
| `gymnasium` | 194 | The environment interface | pure |
| `stable-baselines3` | 201 | The PPO implementation | pure |
| `optuna` | 211 | Study infrastructure | pure |

Two of these assignments are judgements rather than readings, and are recorded as
such in the survey's own `reason` fields: no phase names a wallet adapter or an
algo adapter, so each is placed against the phase whose work the package serves.

---

## What the survey found

Surveyed on 2026-08-16, against CPython 3.14 on `win_amd64`.

**Every library the programme schedules has a wheel.** There is no gap, so
[`runtime-contract.toml`](runtime-contract.toml) is unchanged by this phase. That
is the answer ADR-0051 was waiting for, and it is the outcome in which the phase
looks like a formality — which is exactly why it had to be done rather than
assumed.

Three findings are worth carrying forward.

### The Binance SDK family caps at `<3.15`

`binance-common` and every `binance-sdk-*` distribution publishes
`Requires-Python = "<3.15,>=3.10"`. An **upper** bound, uniform across the family.

The pinned line satisfies it. The next one would not. ADR-0050 chose an exact
minor line rather than a floor, on the argument that a repository verified on 3.14
has not been verified on 3.15; this is independent evidence that the shape of that
decision was right, from the one dependency the system cannot do without. The
probe watches it, because a cap tightening to `<3.14` is the change that would
matter most and would otherwise arrive silently.

### One library would block a free-threaded build

ADR-0050 refused free-threaded builds because *"Phase 018 has not yet surveyed
whether the planned stack publishes for it"*. It has now.

Of the surveyed set, exactly one — `ta-lib` — publishes `cp314-cp314` and no
`cp314t`. Every pure-Python entry serves a free-threaded build because `py3-none`
binds to no ABI; so do `xgboost` and `lightgbm`, for the same reason; and `numpy`,
`pandas` and `torch` publish `cp314t` explicitly.

**One blocker is enough to keep the refusal standing.** The gate reports it and
does not fail on it: a gap there is the refusal being correct, not something going
wrong, and failing would make the gate red for holding the position the project
deliberately holds. The day that list empties is the day the decision is worth
reopening.

### The prerelease refusal is untouched by this survey

ADR-0050 also refused prereleases. Nothing here bears on it — the survey read
final releases and says nothing about what a prerelease would publish — and it is
recorded as unexamined rather than quietly counted as confirmed.

---

## What is deliberately not surveyed

Silence must not read as a gap, so the omissions are stated.

| Not surveyed | Why |
|---|---|
| Storage engines | Phase 097 **selects** them. Surveying a candidate would pre-empt the selection that phase exists to make. |
| Indicator libraries other than TA-Lib | Phase 113 **selects** them. TA-Lib is here because Phases 025 and 114 name it. |
| A Telegram client library | The Phase 001 ledger records an HTTP API, not a package. No phase schedules a wrapper. |
| Transport libraries | The Binance SDK carries its own; Phases 045-046 build on that rather than choosing separately. |
| `scipy`, `scikit-learn` and similar | They arrive transitively behind the entries that are surveyed. Nothing in the roadmap schedules them by name. |
| CUDA builds of PyTorch | Served from a separate index, and which one performs on this host is a measurement Phases 023-024 make. |

`numpy` and `pandas` **were** here, and are the one place the survey named packages
the roadmap describes only as a capability — Phase 022's *numerical and dataframe
stack*. That judgement was recorded in their entries and made because four other
surveyed libraries require them.

**They left in Phase 022, when that phase delivered.** ADR-0052 is explicit that a
survey entry naming a phase which has already shipped is "an adoption wearing a
survey's clothes", and `phase_problems` in the gate refuses one. `DELIVERED_PHASE`
rose from `18` to `22` in the same commit — the first time since Phase 018 that the
survey actually changed.

**The question moved rather than closed.** This file asks whether a wheel exists.
Once a library is installed, what remains is whether the thing inside it computes
correctly, which no filename can settle.
[`stack-contract.toml`](stack-contract.toml) now holds those two entries and
`python -m tools.quality stack` recomputes them from measurement; the reasoning is
in [`SCIENTIFIC_STACK.md`](SCIENTIFIC_STACK.md) and
[ADR-0058](../adr/0058-the-scientific-stack-is-verified-by-measurement-and-stays-in-the-approximate-regime.md).

Both remain required transitively by several surveyed entries. That is not a
reason to re-list them: a transitive dependency is covered by the wheel of the
library that pulls it in, and restating it here would make this file the source of
a claim it has stopped being responsible for.

---

## Adding an entry

1. Read the distribution's own metadata at `https://pypi.org/pypi/<name>/json`.
   Record the canonical location and the access date in that phase's ledger under
   [`../research/`](../research/), per [`../SOURCE_POLICY.md`](../SOURCE_POLICY.md).
2. Add a `[[library]]` to [`wheel-survey.toml`](wheel-survey.toml) with the
   version, the published `Requires-Python`, the wheel filenames that could serve
   the target line, the verdict, the source, and a `reason` naming the phase's
   claim on it.
3. If there is no wheel, add `resolved_by` naming the phase that must close the
   gap.
4. Run both commands. The check recomputes the verdict; the probe confirms the
   record against the index.

Do not add a library because it looks useful. `phase` is a claim that the roadmap
schedules it, and the gate checks that the phase exists and has not shipped.

---

## Related

- [`wheel-survey.toml`](wheel-survey.toml) — the survey itself
- [`RUNTIME_BASELINE.md`](RUNTIME_BASELINE.md) — the interpreter this surveys against
- [`runtime-contract.toml`](runtime-contract.toml) — and its machine-readable half
- [`../DEPENDENCY_POLICY.md`](../DEPENDENCY_POLICY.md) — how a library becomes a dependency
- [`QUALITY_GATES.md`](QUALITY_GATES.md) — which checks are mandatory
- [ADR-0050](../adr/0050-the-runtime-is-a-declared-contract-and-venv-is-its-only-environment.md) — the pin, and the two refusals this survey answers
- [ADR-0051](../adr/0051-phase-017-absorbs-interpreter-pinning-and-the-environment-lifecycle.md) — why this phase exists and what it may change
- [ADR-0052](../adr/0052-wheel-availability-is-a-recorded-survey-whose-verdict-is-recomputed.md) — the decisions behind this document
