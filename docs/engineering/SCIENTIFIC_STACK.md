# The scientific stack

What GLOBIN assumes about `numpy` and `pandas`, how those assumptions are checked,
and what a failure means.

**This reaches no network.** No index is consulted, no resolver runs and `pip` is
never invoked. Everything here is answerable from the files in this repository and
the libraries installed on this machine.

The decisions are in
[ADR-0058](../adr/0058-the-scientific-stack-is-verified-by-measurement-and-stays-in-the-approximate-regime.md).
This document is how to use what that decided.

---

## Why a gate rather than an import check

Phase 021 declared both libraries, reviewed each against
[`../DEPENDENCY_POLICY.md`](../DEPENDENCY_POLICY.md), and pinned them in
`pylock.toml`. It said in
[ADR-0055](../adr/0055-the-first-runtime-dependencies-are-introduced-and-globin-becomes-installed.md)
that it made "no claim about numerical correctness".

Phase 018 had already drawn the line this phase stands on:
[ADR-0052](../adr/0052-wheel-availability-is-a-recorded-survey-whose-verdict-is-recomputed.md)
established that a published wheel filename is a claim about **availability**, not
about behaviour, and [`../research/phase_018_sources.md`](../research/phase_018_sources.md)
filed *"whether each wheel, once installed, actually works on this host"* against
Phase 022 by name.

So the question was never "is it installed" — the lock already answers that. A
check concluding the stack is fine because `import numpy` did not raise proves a
file was found. It says nothing about whether `float64` on this host is the type
every later phase's arithmetic assumes it is.

---

## Running it

```bash
python -m tools.quality stack
```

It reads [`stack-contract.toml`](stack-contract.toml), measures this environment,
recomputes every verdict, and writes `.globin/stack/stack-manifest.json`.

**Run it through the project environment.** `numpy` and `pandas` arrive with the
runtime lock, which only `.venv` installs. Through a bare interpreter the gate
correctly reports two libraries that are not installed — a true answer to the
wrong question.

```bash
.venv\Scripts\python.exe -m tools.quality stack
```

It is **not** in `full`, alongside `governance`, `release`, `runtime`, `wheels`,
`drift` and `lock`: it writes an artefact, and it is the slowest gate here by an
order of magnitude because it imports both libraries to measure them. What must
gate a commit is in `tests/contract/test_stack_contract.py`, which the ordinary
suite runs.

| Exit code | Meaning |
|---:|---|
| 0 | Every check passed |
| 1 | A check failed |
| 2 | The command line was not understood |
| 3 | A check could not be measured, which is never a pass |

---

## What it checks

### Four registers must agree

A version is written down in four places, and the gate's first job is to hold them
against each other.

| Register | Says |
|---|---|
| `pyproject.toml` | The lower bound GLOBIN requires |
| `pylock.toml` | The exact version pinned, with its digest |
| The installed `.dist-info` | What actually landed in this environment |
| [`stack-contract.toml`](stack-contract.toml) | What the behavioural claims were established against |

A fourth register is only worth adding because something compares all four. If it
did not, this file would be a place for a version to go stale.

### Provenance is read from the artefact

The digest in `pylock.toml` says what *should* have been fetched. The `Tag:` line
in the installed `.dist-info/WHEEL` says what is actually unpacked. The gate reads
the second.

That is what catches a wheel built for another ABI — `cp314t` instead of `cp314`,
another minor line, another architecture. Such a wheel installs cleanly, satisfies
its digest, and then behaves like a library compiled for a different interpreter.

### Identity

The imported module must resolve inside the project environment. A `numpy`
shadowed by a stray directory earlier on the path is a different library from the
one the lock pinned, and no digest says anything about which one an import finds.

### Seven behaviour probes

Each defends an assumption written down somewhere in this repository. The
`because` field in the declaration names which one.

| Probe | Defends |
|---|---|
| `numpy.float64_is_binary64` | [`../PRECISION_POLICY.md`](../PRECISION_POLICY.md) defines the approximate regime in terms of IEEE-754 binary64 |
| `numpy.nan_and_infinity_propagate` | A substituted finite value is a plausible number nothing downstream can question |
| `numpy.integer_overflow_wraps_observably` | Overflow may wrap; it may not be silent |
| `pandas.float64_round_trip_is_bit_exact` | A frame that altered a float would break reproducibility |
| `pandas.missing_value_survives_a_round_trip` | A missing value becoming `0.0` is corruption with no detectable signature |
| `pandas.utc_timestamp_round_trip_preserves_the_instant` | [`../TIME_POLICY.md`](../TIME_POLICY.md) makes internal time UTC and aware |
| `pandas.copy_on_write_is_active` | Without it, a function taking a slice can mutate its caller's data |

**The probes assert on behaviour, never on a version number or an option.** pandas
3.0 removed the ability to disable copy-on-write and deprecated
`mode.copy_on_write`; a probe reading that option would emit a warning today and
fail outright on pandas 4 for a reason unrelated to whether GLOBIN's assumption
still holds. A contract test enforces that no probe reads it.

---

## Verification is not adoption

**Nothing under `src/globin` imports `numpy` or `pandas`, and
`tests/architecture/test_stack_discipline.py` fails if anything starts.**

[`../PRECISION_POLICY.md`](../PRECISION_POLICY.md) rule 1 is a one-way door: a
`float` may never be the last transformation before a venue or a ledger, and may
never decide a refusal. These libraries live entirely in the approximate regime.
They may never carry a `Price` or a `Quantity`.

The tripwire is not a prohibition forever. The phase with a legitimate use edits
the stack contract **in its own diff**, where the decision is visible — rather
than discovering the door was already open. The set it guards is derived from the
declaration, so a library added there is covered without anybody remembering to
add it twice.

---

## Adding a library

1. Get it into `project.dependencies` with a written review under
   [`../DEPENDENCY_POLICY.md`](../DEPENDENCY_POLICY.md) and into `pylock.toml`.
   This file may only describe libraries GLOBIN actually depends on; a contract
   test enforces it.
2. Add a `[[library]]` entry with the version, the wheel tag its artefact records,
   its role, and **at least one probe**. A library with no probe is a dependency
   wearing a contract's clothes.
3. Add a `[[probe]]` entry per probe, with a `because` naming the GLOBIN document
   whose rule the probe defends. A probe that cannot name one is decoration.
4. Implement the expectation in `tools/quality/stack/plan.py` and the measurement
   in `tools/quality/stack/probes.py`. The two registries are compared against the
   declaration in both directions, so a half-added probe fails rather than
   silently doing nothing.
5. Remove its entry from [`wheel-survey.toml`](wheel-survey.toml) if it has one —
   see below.

---

## The handoff from the wheel survey

[`wheel-survey.toml`](wheel-survey.toml) asks whether a wheel **exists** for the
pinned interpreter. Once a library is installed, the remaining question is whether
the thing inside that wheel **computes correctly**, which no filename can settle.

So when a library is adopted, its survey entry moves here. That is not tidiness:
`tools/quality/wheels/gate.py` refuses an entry naming a phase that has already
shipped, on ADR-0052's grounds that it would be "an adoption wearing a survey's
clothes". `numpy` and `pandas` left the survey in Phase 022, and `DELIVERED_PHASE`
rose from `18` to `22` in the same commit.

---

## Reading a failure

| Finding | What it means | First move |
|---|---|---|
| `versions` | The four registers disagree | Rebuild `.venv` from the lock; if the lock and the manifest disagree, one of them was edited alone |
| `provenance` | The installed wheel was built for another interpreter | Rebuild `.venv`; a `cp314t` tag means a free-threaded build got in |
| `identity` | The import resolves somewhere unexpected, or not at all | Something shadows the library on `sys.path` |
| `probes` (failed) | A numeric assumption stopped holding | Read the probe's `because`; this is the case worth escalating rather than patching |
| `probes` (unmeasured) | The library would not import | Not a numeric failure — fix the environment first |
| `target` | The stack was verified against an interpreter the runtime contract no longer declares | Phase 017 owns the contract; the stack claims must be re-established on the new line |
| `registry`, `coverage`, `duplicates`, `deferrals` | The declaration disagrees with itself or with the code | Nothing about the machine is wrong; this file is |

A failing probe is the one finding that is **not** routinely an environment
problem. The others usually mean the install is wrong; a probe failure means a
library this project depends on stopped doing something this project assumes, and
that is worth reading upstream's release notes over.

---

## What this does not decide

Named so that silence does not read as a gap, and so nobody cites a green stack
gate as evidence for a question it never asked. Each also appears as a
`[[deferral]]` in the declaration, where a contract test holds it to naming a
phase that has not shipped.

| Question | Phase |
|---|---|
| The numeric type indicators and models use, and its tolerance | 113 |
| Bit-identical reproducibility of a float computation across hosts | 158 |
| Whether a GPU accelerates any of this, and whether one is present | 023 |
| The native TA-Lib library the Python wrapper requires | 025 |
| Which storage engine and columnar format persist these frames | 097 |

Seven behaviours are not the whole of two large libraries, and this gate does not
pretend otherwise. What it establishes is that *the specific assumptions GLOBIN has
written down* hold here. ADR-0058 records why upstream's own test suites are
deliberately not run.
