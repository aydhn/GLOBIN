# Phase 018 — Source Ledger

Wheel Availability Survey for the Planned Stack; the tag rules the survey applies,
and the distribution metadata it applies them to.

Every claim Phase 018 makes about an external system is recorded here, per
[`../SOURCE_POLICY.md`](../SOURCE_POLICY.md). Where a source was *read*, the
sentence it supports is quoted; where a distribution was *probed*, the filenames
are written out, on the pattern Phases 014-017 established: "the library has a
wheel" is a claim, and a filename is evidence.

This phase reads more than it probes in one sense and probes more in another.
Three entries below are specifications — they decide what a filename *means*, and
getting them wrong would make every conclusion here confidently incorrect. The
rest are distribution metadata, read on one day, whose whole purpose is to be
compared against the same metadata later.

**Every distribution below was read on 2026-08-16 through the interface in S-04,
and the survey records the filenames verbatim.** They are not restated in full
here; [`../engineering/wheel-survey.toml`](../engineering/wheel-survey.toml) is
the record, and this ledger says where each came from and what it settled.

---

## The rules a filename is read by

### S-01 — The wheel filename convention

- **Canonical location:** Python Packaging User Guide, *Binary distribution
  format* — `https://packaging.python.org/en/latest/specifications/binary-distribution-format/`
- **Accessed:** 2026-08-16
- **Authority:** Primary — the packaging specification itself.
- **Supports:** "The wheel filename is
  `{distribution}-{version}(-{build tag})?-{python tag}-{abi tag}-{platform tag}.whl`",
  and of the optional build tag: "Must start with a digit. Acts as a tie-breaker
  if two wheel file names are the same in all other respects."
- **Implication for GLOBIN:** The parser in
  [`tools/quality/wheels/plan.py`](../../tools/quality/wheels/plan.py) implements
  exactly this grammar, including the build tag's leading-digit rule. That rule is
  load-bearing rather than pedantic: without it a build tag is indistinguishable
  from part of the version, and every recorded version would look wrong for the
  minority of wheels that carry one.

### S-02 — Compatibility tags, and what `none`, `any` and `abi3` mean

- **Canonical location:** Python Packaging User Guide, *Platform compatibility
  tags* — `https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/`
- **Accessed:** 2026-08-16
- **Authority:** Primary — the packaging specification, superseding PEP 425 as the
  living document.
- **Supports:** "The tag format is `{python tag}-{abi tag}-{platform tag}`", with
  `none` given as an abi tag and `any` as a platform tag. "For example, the tag
  `py27-none-any` indicates compatibility with Python 2.7 (any Python 2.7
  implementation) with no abi requirement, on any platform." And of the stable
  ABI: "The CPython stable ABI is `abi3` as in the shared library suffix."
- **Implication for GLOBIN:** Compatibility is decided by the interpreter tag
  *paired with* the ABI tag, not by either alone. An abi tag of `none` means no ABI
  requirement, which is why `xgboost`'s `py3-none-win_amd64` wheel is installable
  on the pinned interpreter despite naming no CPython version — the finding a
  substring search for `cp314` would have reported as a gap.

### S-03 — PEP 425, the historical decision

- **Canonical location:** `https://peps.python.org/pep-0425/`
- **Accessed:** 2026-08-16
- **Authority:** Primary — the accepted proposal the specification descends from.
- **Supports:** *Compatibility Tags for Built Distributions*, which introduced the
  three-part tag and the compressed tag set (`py2.py3`).
- **Implication for GLOBIN:** Recorded so that the specification in S-02 is read
  as the current statement of a decision rather than as the decision itself. The
  compressed tag set is why the parser expands `py2.py3` once, at parse time,
  instead of at every comparison.

### S-04 — The free-threaded build supports neither the Limited C API nor the stable ABI

- **Canonical location:** Python documentation, *C API Extension Support for Free
  Threading* — `https://docs.python.org/3/howto/free-threading-extensions.html`
- **Accessed:** 2026-08-16
- **Authority:** Primary — CPython's own documentation.
- **Supports:** "The free-threaded build does not currently support the Limited C
  API or the stable ABI." And, on distribution: "You will need to build separate
  wheels specifically for the free-threaded build." The build is identified by a
  `t` suffix, "such as `python3.14t`".
- **Implication for GLOBIN:** This settles the one rule in the matcher that could
  not be inferred from S-02, and it settles it against the intuitive answer. An
  `abi3` wheel is **not** a route onto a free-threaded interpreter, so counting one
  as coverage would understate the cost of adopting that build. Combined with the
  separate-wheels requirement, it means `cp314-cp314` and `cp314-cp314t` never
  substitute for each other in either direction — which is what makes `ta-lib` a
  genuine blocker rather than an artefact of how the question was asked.

### S-05 — PEP 703, why a free-threaded build exists at all

- **Canonical location:** `https://peps.python.org/pep-0703/`
- **Accessed:** 2026-08-16
- **Authority:** Primary — the accepted proposal.
- **Supports:** *Making the Global Interpreter Lock Optional in CPython*.
- **Implication for GLOBIN:** Context for
  [ADR-0050](../adr/0050-the-runtime-is-a-declared-contract-and-venv-is-its-only-environment.md)'s
  refusal rather than evidence against it. The refusal rests on wheel
  availability, which S-04 and the survey answer; whether a free-threaded
  interpreter would *benefit* this system is a measurement no phase has made.

### S-06 — The PyPI JSON API

- **Canonical location:** PyPI documentation, *JSON API* — `https://docs.pypi.org/api/json/`
- **Accessed:** 2026-08-16
- **Authority:** Primary — the index's own published interface.
- **Supports:** The per-project endpoint `https://pypi.org/pypi/<name>/json`,
  returning an `info` object carrying `version` and `requires_python`, and a
  `urls` array whose entries carry `filename`.
- **Implication for GLOBIN:** This is the documented interface every entry below
  was read through, and the one
  [`tools/quality/wheels/gate.py`](../../tools/quality/wheels/gate.py) re-reads on
  `probe`. It is a public, unauthenticated endpoint: no credential is used, none
  is stored, and the survey configures no private index. Reading a documented API
  rather than parsing the web interface is [ADR-0004](../adr/0004-official-apis-only-no-scraping.md)'s
  rule applied outside the exchange.

---

## The stack, as the index published it on 2026-08-16

### S-07 — NumPy

- **Canonical location:** `https://pypi.org/pypi/numpy/json`
- **Accessed:** 2026-08-16
- **Authority:** Primary — upstream distribution metadata.
- **Supports:** Version 2.5.2, requiring Python 3.12 or later. Publishes
  `numpy-2.5.2-cp314-cp314-win_amd64.whl` **and**
  `numpy-2.5.2-cp314-cp314t-win_amd64.whl`, alongside wheels for 3.12, 3.13 and
  3.15.
- **Implication for GLOBIN:** The numerical half of Phase 022's stack installs on
  the pinned line, and on its free-threaded variant. The presence of `cp315`
  wheels is noted and deliberately not acted on: what a later interpreter line
  publishes is not a reason to move to it, and S-13 gives a concrete reason not to.

### S-08 — pandas

- **Canonical location:** `https://pypi.org/pypi/pandas/json`
- **Accessed:** 2026-08-16
- **Authority:** Primary — upstream distribution metadata.
- **Supports:** Version 3.0.5, requiring Python 3.11 or later. Publishes
  `pandas-3.0.5-cp314-cp314-win_amd64.whl` and
  `pandas-3.0.5-cp314-cp314t-win_amd64.whl`.
- **Implication for GLOBIN:** The dataframe half of Phase 022's stack, on the same
  terms as S-07.

### S-09 — TA-Lib Python wrapper

- **Canonical location:** `https://pypi.org/pypi/ta-lib/json`
- **Accessed:** 2026-08-16
- **Authority:** Primary — upstream distribution metadata.
- **Supports:** Version 0.7.1, requiring Python 3.9 or later. Publishes
  `ta_lib-0.7.1-cp314-cp314-win_amd64.whl`, and Windows wheels back to CPython
  3.9. **No `cp314t` wheel is published.**
- **Implication for GLOBIN:** Two separate conclusions, and conflating them would
  be the mistake. First, a binary wheel for the pinned line exists — which is a
  narrower claim than "TA-Lib is provisioned", because Phase 001's S-16 records
  that the wrapper requires the native C library and whether this wheel carries it
  is Phase 025's measurement rather than a filename's to make. Second, this is the
  **only** entry in the survey with no free-threaded wheel, and therefore the
  single library that would block a free-threaded build today.

### S-10 — XGBoost

- **Canonical location:** `https://pypi.org/pypi/xgboost/json`
- **Accessed:** 2026-08-16
- **Authority:** Primary — upstream distribution metadata.
- **Supports:** Version 3.4.1, requiring Python 3.12 or later. Publishes exactly
  one Windows wheel: `xgboost-3.4.1-py3-none-win_amd64.whl`. There is no
  `cp314` wheel and no `cp314t` wheel.
- **Implication for GLOBIN:** The entry that shaped the matcher. `py3-none` is
  platform-specific and interpreter-agnostic — a native library loaded through
  `ctypes` rather than built against a Python ABI — so by S-02 it installs on the
  pinned interpreter and, having no ABI requirement, on the free-threaded build as
  well. A survey searching filenames for `cp314` would have reported a gap here
  and sent this phase to reopen the interpreter contract over nothing. XGBoost also
  remains the strictest interpreter floor in the stack, as Phase 001's S-11 found.

### S-11 — LightGBM

- **Canonical location:** `https://pypi.org/pypi/lightgbm/json`
- **Accessed:** 2026-08-16
- **Authority:** Primary — upstream distribution metadata.
- **Supports:** Version 4.7.0, requiring Python 3.10 or later. Publishes
  `lightgbm-4.7.0-py3-none-win_amd64.whl` as its only Windows wheel.
- **Implication for GLOBIN:** Installable on the pinned line for the reason S-10
  gives. The wheel is a CPU build; Phase 001's S-12 records that CUDA support
  requires building from source and that the project states CUDA is unsupported
  for Windows users. That is a capability question this survey does not answer and
  Phases 023-024 do.

### S-12 — PyTorch

- **Canonical location:** `https://pypi.org/pypi/torch/json`
- **Accessed:** 2026-08-16
- **Authority:** Primary — upstream distribution metadata.
- **Supports:** Version 2.13.0, requiring Python 3.10 or later. Publishes
  `torch-2.13.0-cp314-cp314-win_amd64.whl` and
  `torch-2.13.0-cp314-cp314t-win_amd64.whl`, alongside Windows wheels for 3.10
  through 3.13.
- **Implication for GLOBIN:** Phase 183's neural models and Phase 201's PPO
  implementation both rest on this, and both are served on the pinned line. These
  are the default PyPI wheels; a CUDA build is served from a separate index, and
  which one installs and performs on this host is recorded as unresolved in Phase
  001's ledger against Phases 023-024.

### S-13 — The Binance official Python SDK family

- **Canonical location:** `https://pypi.org/pypi/binance-sdk-spot/json`, and the
  sibling endpoints for `binance-common`, `binance-sdk-margin-trading`,
  `binance-sdk-derivatives-trading-usds-futures`,
  `binance-sdk-derivatives-trading-coin-futures`,
  `binance-sdk-derivatives-trading-options`,
  `binance-sdk-derivatives-trading-portfolio-margin`,
  `binance-sdk-derivatives-trading-portfolio-margin-pro`,
  `binance-sdk-wallet` and `binance-sdk-algo`
- **Accessed:** 2026-08-16
- **Authority:** Primary — the vendor's own published distribution metadata, for
  the monorepo Phase 001's S-07 documented.
- **Supports:** Ten distributions, each publishing a single `py3-none-any` wheel,
  at versions from 3.1.0 (`algo`) to 17.0.1 (`usds-futures`). **Every one of them
  declares `Requires-Python = "<3.15,>=3.10"`** — a floor *and a cap*, identical
  across the family.
- **Implication for GLOBIN:** The sharpest finding of the phase, and the only one
  that constrains a future decision rather than confirming a past one. Being pure
  Python, these install on any interpreter in range, including a free-threaded
  build. But the range has a ceiling: CPython 3.14 satisfies it and 3.15 would
  not. [ADR-0050](../adr/0050-the-runtime-is-a-declared-contract-and-venv-is-its-only-environment.md)
  chose an exact minor line rather than a floor on the argument that a repository
  verified on 3.14 has not been verified on 3.15; this is independent evidence
  that the shape of that decision was right, arriving from the one dependency the
  system cannot operate without. A cap tightening to `<3.14` is the change that
  would matter most here, and `python -m tools.quality.wheels probe` watches for it.

### S-14 — Gymnasium

- **Canonical location:** `https://pypi.org/pypi/gymnasium/json`
- **Accessed:** 2026-08-16
- **Authority:** Primary — upstream distribution metadata.
- **Supports:** Version 1.3.0, requiring Python 3.10 or later. One wheel:
  `gymnasium-1.3.0-py3-none-any.whl`.
- **Implication for GLOBIN:** Phase 194's environment interface is pure Python and
  imposes no constraint on the interpreter line.

### S-15 — Stable-Baselines3

- **Canonical location:** `https://pypi.org/pypi/stable-baselines3/json`
- **Accessed:** 2026-08-16
- **Authority:** Primary — upstream distribution metadata.
- **Supports:** Version 2.9.0, requiring Python 3.10 or later. One wheel:
  `stable_baselines3-2.9.0-py3-none-any.whl`.
- **Implication for GLOBIN:** Phase 201's PPO agent. Its own wheel is indifferent
  to the interpreter, but it runs on PyTorch, so S-12 is where the real constraint
  sits. Recording that distinction matters: a survey that read this entry alone
  would conclude the reinforcement-learning band has no interpreter constraint at
  all.

### S-16 — Optuna

- **Canonical location:** `https://pypi.org/pypi/optuna/json`
- **Accessed:** 2026-08-16
- **Authority:** Primary — upstream distribution metadata.
- **Supports:** Version 4.9.0, requiring Python 3.9 or later. One wheel:
  `optuna-4.9.0-py3-none-any.whl`.
- **Implication for GLOBIN:** Phase 211's study infrastructure is pure Python. Its
  durable storage is a database question Phase 097 owns, not a wheel question.

---

## Facts deliberately left unverified in Phase 018

The following are relevant but were not settled here, because settling them
requires either measurement on this machine or work belonging to a later phase.
They are recorded so that no later phase mistakes silence for confirmation.

| Question | Why unresolved | Phase that must resolve it |
|---|---|---|
| Whether each wheel, once installed, actually works on this host | A published filename is a claim about availability, not about behaviour | 022 |
| Whether the TA-Lib wheel carries the native C library or still requires it separately | Requires installing it and observing, not reading metadata | 025 |
| Which CUDA build of PyTorch installs and performs here | Served from a separate index, and answerable only by measurement | 023-024 |
| Whether the full set resolves together without conflicting transitive requirements | No resolver was run; this phase surveys distributions one at a time | 020 |
| Whether prereleases of any of these publish for the pinned line | Only final releases were read, so ADR-0050's prerelease refusal is untouched rather than confirmed | 019 or later |
| Whether a free-threaded interpreter would benefit this system | Wheel availability is settled by S-04 and S-09; benefit is a measurement nobody has made | 023-024 |
| Which storage engine and which indicator library the programme will use | Phases 097 and 113 exist to select them, and surveying a candidate would pre-empt the selection | 097, 113 |
