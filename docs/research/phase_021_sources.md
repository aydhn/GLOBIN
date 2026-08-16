# Phase 021 — Source Ledger

Core Runtime Dependency Introduction, and the application bootstrap delivered
alongside it. What the two adopted distributions publish about themselves, and
what the packaging specifications say about the entry point this phase declares.

Every claim Phase 021 makes about an external system is recorded here, per
[`../SOURCE_POLICY.md`](../SOURCE_POLICY.md).

The phase has two halves and only one of them rests on external evidence. The
dependency half adopts two distributions, and adopting one requires reading what
it says about its own licence, its own supported Python and its own artefacts —
which is what S-01 to S-04 record. The bootstrap half reads nothing outside this
repository: it judges a host against a contract Phase 017 wrote, and the only
external facts it needs are the packaging ones in S-05 and S-06.

**Nothing here was read from a summary site.** A licence aggregator is a
secondary source about a primary fact, and
[`../SOURCE_POLICY.md`](../SOURCE_POLICY.md) makes the project's own published
text authoritative for the project.

---

## The adopted distributions

### S-01 — numpy publishes an SPDX *expression*, not an identifier

- **Canonical location:** `https://pypi.org/pypi/numpy/json`
- **Accessed:** 2026-08-16
- **Authority:** Primary. PyPI serves the metadata the project itself uploaded.
- **Version read:** 2.5.2
- **Supports:** The `info.license_expression` field reads
  `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0`. The deprecated
  `info.license` field is `null` and `info.classifiers` carries no licence
  classifier at all, so the expression is the only statement the project makes.

- **Implication:** `docs/engineering/dependency-reviews.toml` records the
  expression whole rather than reducing it to `BSD-3-Clause`, because reducing it
  would make the register say something the project does not.
  `docs/DEPENDENCY_POLICY.md` gained `0BSD`, `Zlib` and `CC0-1.0` in its allow
  table and a rule for compound expressions: a compound joined by `AND` is allowed
  exactly when every component is. That table had not been extended before, and
  this is the first dependency that forced it.

`OR` expressions are deliberately not covered. `OR` is a choice somebody has to
make and record; none has appeared.

### S-02 — numpy requires Python 3.12 or later

- **Canonical location:** `https://pypi.org/pypi/numpy/json`
- **Accessed:** 2026-08-16
- **Authority:** Primary.
- **Version read:** 2.5.2
- **Supports:** `info.requires_python` reads `>=3.12`.

- **Implication:** Nothing, and that is the point of recording it.
  `pyproject.toml` already declares `requires-python = ">=3.12"`, chosen in
  Phase 001 from XGBoost's floor, so adopting numpy required no change — and a
  future contributor asking whether it did can see that the question was asked.

### S-03 — pandas publishes a single identifier and requires 3.11 or later

- **Canonical location:** `https://github.com/pandas-dev/pandas/blob/main/LICENSE`, corroborated by `https://pypi.org/pypi/pandas/json`
- **Accessed:** 2026-08-16
- **Authority:** Primary. The repository's own licence text; the PyPI metadata is the corroboration rather than the source.
- **Version read:** 3.0.5
- **Supports:** The licence file opens `BSD 3-Clause License`. PyPI's `info.license` carries the
  full text of that file, `info.license_expression` is `null`, and
  `info.classifiers` contains `License :: OSI Approved :: BSD License`.
  `info.requires_python` reads `>=3.11`.

- **Implication:** The review records `BSD-3-Clause`, read from the file
  rather than from the classifier — a classifier names a licence *family* and the
  file names the licence. Both agree here; recording which was authoritative is
  what makes the next disagreement resolvable.

### S-04 — both publish `win_amd64` wheels for the pinned interpreter

- **Canonical location:** `https://pypi.org/pypi/numpy/json`, `https://pypi.org/pypi/pandas/json`; recorded in [`../engineering/wheel-survey.toml`](../engineering/wheel-survey.toml)
- **Accessed:** 2026-08-16 (Phase 018 survey, unchanged)
- **Authority:** Primary.
- **Supports:** `numpy-2.5.2-cp314-cp314-win_amd64.whl` and
  `pandas-3.0.5-cp314-cp314-win_amd64.whl`, both also published for the
  free-threaded ABI.

- **Implication:** That adoption is possible at all on the pinned line, and
  that `pylock.toml`'s recorded wheels can be checked against the runtime contract
  rather than believed. The survey entries stay at `phase = 22`, which is the phase
  that *needs* them; this phase declares and locks, and
  `tools/quality/wheels/plan.py` fails only on a phase already delivered.

---

## Packaging

### S-05 — a console script's generated wrapper calls the entry point with no arguments

- **Canonical location:** `https://packaging.python.org/en/latest/specifications/entry-points/`
- **Accessed:** 2026-08-16
- **Authority:** Primary. PyPA's own specification.
- **Supports:** The `console_scripts` group names an object as `module:qualname`, and an
  installer generates a wrapper that calls it and uses the return value as the
  process exit status.

- **Implication:** `globin.runtime.cli.main` takes every argument with a
  default, so it is callable with none — and
  `tests/contract/test_bootstrap_contract.py` asserts that structurally rather than
  trusting it, because a `main` that grew a required parameter would install
  cleanly and fail on first use.

### S-06 — an editable install exposes the source tree, not a copy

- **Canonical location:** `https://packaging.python.org/en/latest/specifications/pyproject-toml/`, and PEP 660
- **Accessed:** 2026-08-16
- **Authority:** Primary.
- **Supports:** An editable install makes the project importable from its source location rather
  than from a copy taken at install time.

- **Implication:** `scripts/bootstrap.ps1` installs GLOBIN editable, so
  `globin` and `python -m globin` read one tree. A non-editable install would make
  the console script answer about a snapshot, and `globin doctor` exists to be
  trusted about the tree in front of you.

---

## What this phase read nothing about

The bootstrap half judges a Windows host, a CPython interpreter and a virtual
environment against
[`../engineering/runtime-contract.toml`](../engineering/runtime-contract.toml),
which Phase 017 wrote from the sources in
[`phase_017_sources.md`](phase_017_sources.md). Nothing was re-read, because
nothing was re-decided: this phase consumes that contract and does not amend it.

No Binance interface was consulted, and none may be until Phase 033. No
credential store was consulted; what Windows offers one is recorded in
[`phase_020_sources.md`](phase_020_sources.md) and binds Phases 026 to 029, not
this one.
