# Phase 005 — Research Source Ledger

Every external claim made by Phase 5 traces to an entry below. Entries are
summaries written for GLOBIN's purposes; documentation text is not copied into
this repository.

Phase 5 relies on external behaviour in two places: the testing tools it
configures, and the licence and dependency facts that decide whether a new tool
is admissible at all. It relies on no exchange behaviour, because it adds none.

**Ledger conventions**

- `Authority: Primary` means the vendor or upstream project publishing its own
  behaviour. `Secondary` means anything else.
- Several entries record a fact **verified by running the tool in this
  repository**, not only by reading it. Where that happened the entry says so,
  because a behaviour confirmed on the installed version is stronger evidence
  than a documented one — and, in two cases below, the documentation and the
  observed behaviour needed reconciling.
- Where a fact could not be verified from a primary source in this phase, the
  entry says so explicitly and names the phase that must verify it.
- All accesses were performed on the date recorded in each entry.

---

## Property-based testing

### S-01 — Hypothesis: settings reference

- **Canonical location:** https://hypothesis.readthedocs.io/en/latest/reference/api.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the upstream project documenting its own behaviour.
- **Supports:** `max_examples` bounds the number of test cases considered.
  `derandomize=True` seeds the generator from a hash of the test function, so
  every run examines the same cases until the code changes. `database=None`
  disables example storage entirely. `deadline` is a per-example time limit in
  milliseconds, defaulting to 200, and `None` disables it. `print_blob=True`
  prints code usable with `@reproduce_failure` to replay a failing case.
  `settings.register_profile(name, parent=None, **kwargs)` and
  `settings.load_profile(name)` register and activate named configurations.
- **Implication for GLOBIN:** the `dev` and `ci` profiles in `tests/conftest.py`
  are built from exactly these settings. `deadline=None` in both, because a
  per-example time limit is a timing assertion and `filterwarnings = ["error"]`
  would turn its complaint into a hard failure on a shared CI runner.
  `derandomize` and `database=None` are what make the `ci` profile reproducible.

### S-02 — Hypothesis: settings profiles and the pytest plugin

- **Canonical location:** https://hypothesis.readthedocs.io/en/latest/tutorial/settings.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the upstream project documenting its own behaviour.
- **Supports:** profiles are registered in code, and "If using pytest, the
  standard location to place this code is in a `conftest.py` file." A registered
  profile is selected from the command line with `--hypothesis-profile`.
  Registering a profile does not activate it; `load_profile` does.
- **Implication for GLOBIN:** both profiles are registered in
  `tests/conftest.py`, `dev` is loaded there as the default, and the command
  table passes `--hypothesis-profile=ci` on the gate. **Verified by running the
  tool:** `python -m pytest --help` on Hypothesis 6.165.7 lists
  `--hypothesis-profile`, `--hypothesis-seed`, `--hypothesis-verbosity`,
  `--hypothesis-show-statistics` and `--hypothesis-explain`.

### S-03 — Hypothesis: health checks

- **Canonical location:** https://hypothesis.readthedocs.io/en/latest/reference/api.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the upstream project documenting its own behaviour.
- **Supports:** `HealthCheck.function_scoped_fixture` fires when `@given` is
  applied to a test using a pytest function-scoped fixture, because such a
  fixture resets once per test function rather than once per generated case.
- **Implication for GLOBIN:** this phase adds two function-scoped autouse
  fixtures, which raised the question of whether every property test would trip
  the check. **Verified by running the suite:** it does not fire for autouse
  fixtures the test does not itself request, so no health check is suppressed and
  none needed to be. Had it fired, the correct response would have been to
  suppress that one check with the reason recorded, since these guards should
  apply once per test function rather than once per example.

### S-04 — Hypothesis: distribution metadata

- **Canonical location:** https://pypi.org/project/hypothesis/
- **Accessed:** 2026-08-14
- **Authority:** Primary — the project's own published distribution metadata.
- **Supports:** version 6.165.7 declares `License-Expression: MPL-2.0` and one
  unconditional runtime requirement, `sortedcontainers>=2.1.0,<3.0.0`
  (`exceptiongroup` is required only below Python 3.11). Every other requirement
  sits behind an optional extra. `sortedcontainers` is Apache-2.0.
- **Implication for GLOBIN:** admissible under
  [ADR-0003](../adr/0003-zero-budget-open-source-dependency-policy.md) as
  development tooling — both licences are free and open source, and the transitive
  cost is one small pure-Python package. **Verified locally** by reading the
  installed distributions' metadata rather than the web page alone, because the
  page describes the latest release and the repository pins a specific one.

---

## Test isolation and collection

### S-05 — pytest: how to mark test functions

- **Canonical location:** https://docs.pytest.org/en/stable/how-to/mark.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the upstream project documenting its own behaviour.
- **Supports:** custom markers are registered with the `markers` ini option, and
  with strict markers enabled "any unknown marks applied with the
  `@pytest.mark.name_of_the_mark` decorator will trigger an error" rather than a
  warning.
- **Implication for GLOBIN:** the new `property` marker is registered in
  `pyproject.toml` alongside the other nine. Phase 004 already established that
  the strictness must be declared as an ini option rather than in `addopts`; this
  phase changes nothing about that and relies on it.

### S-06 — pytest: fixture instantiation order

- **Canonical location:** https://docs.pytest.org/en/stable/reference/fixtures.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the upstream project documenting its own behaviour.
- **Supports:** fixtures are ordered by scope, then by dependency, then by
  whether they are autouse; higher-scoped fixtures are instantiated first, and a
  fixture's dependencies are instantiated before it. Finalisation runs in reverse.
- **Implication for GLOBIN:** an autouse fixture's dependencies are therefore
  instantiated ahead of it — and ahead of other autouse fixtures declared
  earlier. **Verified by experiment**, because the consequence was not obvious
  from the text: an autouse fixture requesting `monkeypatch` causes
  `monkeypatch` to be torn down *after* a second autouse fixture that inspects
  the environment, so every `monkeypatch.setenv` looks like a leak. The network
  guard therefore saves and restores by hand rather than using `monkeypatch`; see
  [ADR-0024](../adr/0024-tests-are-offline-and-isolated-by-construction.md)
  decision 7.

### S-07 — Python standard library: `unittest.mock` autospeccing

- **Canonical location:** https://docs.python.org/3/library/unittest.mock.html#autospeccing
- **Accessed:** 2026-08-14
- **Authority:** Primary — the language's own documentation.
- **Supports:** `create_autospec(spec, spec_set=False, instance=False, **kwargs)`
  builds a mock whose attributes and call signatures match the object it
  replaces, raising `TypeError` on a wrong-signature call. `spec_set` is the
  stricter variant, refusing to get *or set* an attribute the spec lacks. The
  documentation recommends autospeccing so that "your mocks will fail in the same
  way as your production code if they are used incorrectly."
- **Implication for GLOBIN:** hand-written doubles satisfying a `Protocol` remain
  the default, because they prove a port is a real seam. Where a mock is
  genuinely the right tool, `TESTING_STRATEGY.md` now requires
  `create_autospec(..., spec_set=True)`, and the one such double in the suite —
  standing in for `tools.quality.runner.run` — uses it.

### S-08 — Python standard library: `socket` connection entry points

- **Canonical location:** https://docs.python.org/3/library/socket.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the language's own documentation.
- **Supports:** `socket.create_connection` is a convenience function that
  resolves an address and connects; `socket.socket.connect` and
  `socket.socket.connect_ex` are the underlying methods, the latter returning an
  error indicator rather than raising.
- **Implication for GLOBIN:** the offline guard patches all three. Guarding only
  `create_connection` would leave any caller that builds its own socket
  unaffected, which is exactly what a hand-written transport does.

### S-09 — RFC 5737: IPv4 address blocks reserved for documentation

- **Canonical location:** https://www.rfc-editor.org/rfc/rfc5737
- **Accessed:** 2026-08-14
- **Authority:** Primary — the standards document defining the reservation.
- **Supports:** `192.0.2.0/24` (TEST-NET-1) is reserved for documentation and
  examples and is not globally routable.
- **Implication for GLOBIN:** the test that proves the network guard refuses a
  connection aims at `192.0.2.1`. If the guard ever failed open, the attempt
  would time out rather than reach a real host.

---

## Coverage measurement

### S-10 — Coverage.py: branch coverage

- **Canonical location:** https://coverage.readthedocs.io/en/latest/branch.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the upstream project documenting its own behaviour.
- **Supports:** branch coverage records transitions between lines rather than
  line execution alone, so a conditional whose alternative arm never runs is
  reported as a partial branch. The percentage counts each branch destination as
  an additional opportunity, so enabling it lowers the figure for the same tests.
  Missing branches are shown as `source->destination`.
- **Implication for GLOBIN:** Phase 004 already enabled `branch = true`. This
  phase used the partial-branch column to find genuinely untested decisions —
  the `find_spec` failure arm in `tools/quality/runner.py`, and the paths added
  by the error-taxonomy migration — rather than to raise a number.

### S-11 — Coverage.py: configuration reference

- **Canonical location:** https://coverage.readthedocs.io/en/latest/config.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the upstream project documenting its own behaviour.
- **Supports:** `fail_under` exits with a non-zero status when total coverage
  falls below the given percentage, and the total includes branch measurements
  when `branch` is enabled. `exclude_also` adds to coverage's built-in exclusion
  patterns, whereas `exclude_lines` replaces them.
- **Implication for GLOBIN:** the floor stays at 95 while measured coverage is
  99.57%. Both `QUALITY_GATES.md` and `TESTING_STRATEGY.md` state the threshold
  is a regression detector rather than a target, so this phase deliberately did
  not raise it — doing so in a phase about test quality would have contradicted
  the documents it was extending.

---

## Facts deliberately left unverified in Phase 5

| Question | Why unresolved | Phase that must resolve it |
|---|---|---|
| Whether the pinned tool versions resolve together from a lockfile | Phase 5 pins exact versions in CI as a reproducibility measure, not a lockfile. No resolver has been run. | 020 |
| Whether Hypothesis behaves identically on Python 3.12 and 3.14 | Only 3.14.5 was exercised locally. CI runs both, but had not yet run against this commit when the phase was written. | 018, and the next CI run |
| Whether `derandomize` remains stable across Hypothesis minor releases | The setting is documented, but reproducibility across versions is not promised anywhere consulted. | 020, with the lockfile |
| Whether the offline guard holds for libraries using non-socket transports | No such library is present. The guard covers the three documented socket entry points and nothing else. | 033-048 |
