# Phase 030 — Source Ledger

Every external claim Phase 030 relied on, where it was read, and what GLOBIN does
differently because of it. The rules this ledger follows are in
[`../SOURCE_POLICY.md`](../SOURCE_POLICY.md).

This phase has two halves — the bootstrap health check suite its title names, and
the configuration evidence surface delivered as the fourteenth scope amendment — and
neither reaches a network. Most of what had to be established was therefore about
*this* repository and *this* host rather than about an external interface, so the
majority of entries below are marked **Probe**: measured here, with the command
recorded, rather than read and believed. **Four of them changed an implementation
decision**, which is said in bold where it happened.

**No Binance documentation was consulted, and that omission is the decision rather
than an oversight.** Nothing in this phase touches a venue, a URL, a product or a
credential's use. What an environment *is* remains Phase 035's and which product and
environment pairs are usable remains Phase 036's; a profile still names a document
rather than an environment, which `as_config` enforces structurally, since no
registered key can say anything about a venue.

---

### S-01 — `tomllib` parses TOML and provides no writing API

- **Canonical location:** Python documentation, `tomllib` — Parse TOML files —
  `https://docs.python.org/3/library/tomllib.html`
- **Accessed:** 2026-08-18
- **Authority:** Primary — the standard library's own documentation.
- **Supports:** The module exposes `load` and `loads` and no serialising
  counterpart, and the documentation states that it does not support writing TOML.
- **Implication for GLOBIN:** Confirms the property
  `CONFIGURATION_LAYOUT.md` already rests on and Phase 030 now leans on twice: the
  `config` command group is structurally incapable of editing an operator's
  document, so "five verbs and every one of them reads" is a fact about the parser
  rather than a rule somebody keeps. No writing verb was designed.

### S-02 — `tomllib.TOMLDecodeError` derives from `ValueError`

- **Canonical location:** Python documentation, `tomllib.TOMLDecodeError` —
  `https://docs.python.org/3/library/tomllib.html#tomllib.TOMLDecodeError`
- **Accessed:** 2026-08-18
- **Authority:** Primary.
- **Supports:** The exception is documented as a subclass of `ValueError`.
- **Implication for GLOBIN:** **This changed a decision.** `main` catches
  `(GlobinError, OSError)`, and `TOMLDecodeError` is neither, so a malformed
  document escaped as a traceback. Before this phase that path was unreachable
  rather than handled — every document the chain read was a committed one, and a
  malformed committed document fails the suite. `--config` made it reachable. The
  exception is still not wrapped, which is what `CONFIGURATION_POLICY.md` asks for,
  and the command line now maps it to exit code 14 while keeping the decoder's line
  and column in the message. Measured as S-06.

### S-03 — `argparse` accepts abbreviated long options unless `allow_abbrev` is off

- **Canonical location:** Python documentation, `argparse` — ArgumentParser objects
  — `https://docs.python.org/3/library/argparse.html#allow-abbrev`
- **Accessed:** 2026-08-18
- **Authority:** Primary.
- **Supports:** `allow_abbrev` defaults to `True`, and the documentation describes
  it as allowing long options to be abbreviated to a unique prefix.
- **Implication for GLOBIN:** The phase brief asked for abbreviation to be disabled.
  GLOBIN uses no `argparse` anywhere — ADR-0019 rejected it, and `runtime/cli.py`
  states the same argument for itself — so the requirement is satisfied by a
  property rather than by a setting: every word is compared for equality against a
  spelled constant, so there is no prefix logic to switch off. Four abbreviation
  cases are asserted in `tests/unit/test_config_cli.py` so the property is
  exercised rather than assumed.

### S-04 — Windows environment variable names are case-insensitive, and `os.environ` upper-cases keys on Windows

- **Canonical location:** Python documentation, `os.environ` —
  `https://docs.python.org/3/library/os.html#os.environ`
- **Accessed:** 2026-08-18
- **Authority:** Primary.
- **Supports:** The documentation states that on Windows environment variable keys
  are converted to upper case, because the platform treats them
  case-insensitively.
- **Implication for GLOBIN:** No new mechanism. `environment_variable` already
  derives an upper-case name and `tests/contract/test_configuration_contract.py`
  already asserts the derivation is injective over `known_keys()`, so two keys
  collapsing onto one variable fails the suite rather than making one setting
  silently unreachable. Phase 030 added a command-line layer rather than a second
  environment reader, so nothing here needed extending.

### S-05 — Probe: the declared checks split eleven stable to seven perishable

- **Canonical location:** Measured on this host against the delivered registry. Upstream:
  `https://github.com/aydhn/GLOBIN/blob/master/src/globin/domain/bootstrap.py`
- **Accessed:** 2026-08-18
- **Authority:** Primary — measured, not read.
- **Supports:** Run as
  `.venv\Scripts\python.exe -c "from globin.domain.bootstrap import checks, Durability; ..."`,
  which reported 18 checks, 11 `STABLE` and 7 `PERISHABLE`, with the stable set
  ending at `state.previous_run` and the perishable set beginning at
  `paths.runtime`.
- **Implication for GLOBIN:** The count in `checks()`'s own docstring is the
  measured one rather than a claim. `tests/unit/test_preflight.py` asserts the two
  classes partition the registry, so a nineteenth check cannot land in neither.

### S-06 — Probe: a malformed document named by `--config` escaped `main` as a traceback

- **Canonical location:** Measured on this host, before the fix S-02 describes. What the
  exception is documented to be: `https://docs.python.org/3/library/tomllib.html#tomllib.TOMLDecodeError`
- **Accessed:** 2026-08-18
- **Authority:** Primary — measured.
- **Supports:** `tests/unit/test_config_cli.py::test_malformed_toml_stops_the_command`
  failed with an uncaught `tomllib.TOMLDecodeError` raised through
  `create_dict_rule`, rather than with a non-zero exit code.
- **Implication for GLOBIN:** **This changed a decision.** The clause was added at
  the three places in `runtime/cli.py` that already map faults to exit codes. The
  test was written before the handling existed, which is why it found it.

### S-07 — Probe: an over-broad exception clause changed a Phase 021 exit code

- **Canonical location:** Measured on this host against the existing suite. Upstream:
  `https://github.com/aydhn/GLOBIN/blob/master/tests/unit/test_bootstrap_cli.py`
- **Accessed:** 2026-08-18
- **Authority:** Primary — measured.
- **Supports:**
  `tests/unit/test_bootstrap_cli.py::test_a_run_that_refuses_writes_no_evidence_outside_the_project`
  failed with `assert 14 == ExitCode.INTERNAL` after a `ConfigurationError` clause
  was first added around the whole of `_bootstrap`. That clause was catching
  `Bootstrap.record`'s refusal to write evidence when there is no project root — a
  fault that has answered 17 since Phase 021.
- **Implication for GLOBIN:** **This changed a decision.** The clause was narrowed
  to the one step that can refuse before any check runs, which is the validation of
  `--set` arguments. The reasoning is recorded at the call site rather than only
  here, because the wide version is the one somebody would write again.

### S-08 — Probe: the defaults layer carries model values, not document strings

- **Canonical location:** Measured on this host against the delivered model. What
  `dataclasses.fields` is documented to return:
  `https://docs.python.org/3/library/dataclasses.html#dataclasses.fields`
- **Accessed:** 2026-08-18
- **Authority:** Primary — measured.
- **Supports:** Reading `default_layer()` reported `logging.min_severity` as
  `<Severity.DEBUG: 10>` rather than as `"DEBUG"`, because `section_defaults` reads
  the dataclass defaults.
- **Implication for GLOBIN:** **This changed a decision.** `config dump` reports the
  **bound** model through `effective_values` rather than the resolved layer, and
  renders an enumeration as its name, so a dumped value can be pasted back into a
  document unchanged. Reporting the resolved value would have printed a repr no
  document accepts.

### S-09 — Probe: the same explicit inputs from two working directories fingerprint identically

- **Canonical location:** Measured on this host. Upstream:
  `https://github.com/aydhn/GLOBIN/blob/master/src/globin/domain/config_evidence.py`
- **Accessed:** 2026-08-18
- **Authority:** Primary — measured.
- **Supports:** `globin config fingerprint --config <absolute path> --json` was run
  from the repository root and from `src/`, and both reported
  `semantic_fingerprint` and `evidence_fingerprint` identical.
- **Implication for GLOBIN:** The acceptance criterion the phase brief named is
  satisfied, and the test that pins it asserts the property rather than the
  observed digest — a recorded digest would fail on the next legitimate change to
  the register. `CONFIGURATION_LAYOUT.md`'s stated limitation about implicit
  discovery is unchanged and remains stated: what `--config` gives is an escape
  from it, not a repair of it.

### S-10 — Probe: no baseline reports `unmeasured`, and a changed value reports drift

- **Canonical location:** Measured on this host. Upstream:
  `https://github.com/aydhn/GLOBIN/blob/master/src/globin/adapters/config_evidence.py`
- **Accessed:** 2026-08-18
- **Authority:** Primary — measured.
- **Supports:** `globin config evidence` on a machine with no recorded snapshot
  wrote a manifest whose drift section read `"measured": false`. A second run with
  `--set logging.min_severity=WARNING` reported
  `"changed": ["logging.min_severity"], "semantic_drift": true`.
- **Implication for GLOBIN:** `unmeasured` is a distinct state rather than a clean
  one, which is the treatment `tools/quality/drift` gives an unrecorded baseline. A
  caller that could not tell the two apart would eventually report a machine as
  unchanged because it had never been looked at.

### S-11 — `binance-common` published 4.3.0, under the same interpreter cap as 4.2.0

- **Canonical location:** PyPI JSON API, per-version endpoint —
  `https://pypi.org/pypi/binance-common/4.3.0/json`
- **Accessed:** 2026-08-18
- **Authority:** Primary — the index's own record of the release.
- **Supports:** The release reports `requires_python` of `<3.15,>=3.10` and publishes
  `binance_common-4.3.0-py3-none-any.whl` beside an sdist — the same cap and the same
  pure-Python wheel shape 4.2.0 had.
- **Implication for GLOBIN:** The recorded survey was re-cut for the version alone.
  **The verdict did not change and was not allowed to be assumed**: the cap still
  admits the pinned 3.14 line, and a release that had tightened it would have had to
  change the verdict rather than the version. Nothing is installed, resolved or
  adopted — `binance-common` remains surveyed against Phase 045 and imported nowhere.
  The per-version endpoint was used rather than the package root, because the root
  document is large enough to be truncated by a fetching tool and a truncated read
  once produced a wrong "latest version".
