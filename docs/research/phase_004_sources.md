# Phase 004 — Research Source Ledger

Every external claim made by Phase 4 traces to an entry below. Entries are
summaries written for GLOBIN's purposes; documentation text is not copied into
this repository.

Phase 4 is a tooling phase, so the sources are the documentation of the five
tools the quality gates are built from, plus GitHub's guidance on running them
safely. No Binance source appears, because Phase 4 implements no exchange
behaviour.

Several entries record a fact that was **verified by running the tool in this
repository**, not only read. Where that happened the entry says so, because a
behaviour confirmed on the installed version is stronger evidence than a
documented one — and in the case of S-01 the two initially appeared to disagree,
which is how a three-phase-old configuration defect was found.

**Ledger conventions**

- `Authority: Primary` means the vendor or upstream project publishing its own
  behaviour. `Secondary` means anything else.
- Where a fact could not be verified from a primary source in this phase, the
  entry says so explicitly and names the phase that must verify it.
- All accesses were performed on the date recorded in each entry.

---

## Test framework

### S-01 — pytest: marker registration and strictness options

- **Canonical location:** https://docs.pytest.org/en/stable/reference/reference.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the pytest project documenting its own configuration.
- **Supports:** `strict_markers` is a **configuration option**: when it is set,
  only markers known to pytest, a plugin, or listed in the `markers` setting are
  allowed. The reference lists `strict_config`, `strict_markers`,
  `strict_parametrization_ids` and `strict_xfail` as members of an umbrella
  `strict` option, and states that explicitly setting an individual strictness
  option takes precedence over `strict`. `xfail_strict` is documented as an
  accepted alias for `strict_xfail`.
- **Implication for GLOBIN:** verified against pytest 9.0.3 in this repository,
  and the verification mattered. With `--strict-markers` in `addopts` — the form
  the repository had carried since Phase 001 — an unregistered marker produced a
  `PytestUnknownMarkWarning` and the run **passed**. With `strict_markers = true`
  as an ini option, the same tree failed at collection with
  `'bogus_marker' not found in markers configuration option`. The marker guard
  the repository believed it had was therefore not in force for three phases.
  `pyproject.toml` now declares the ini options, and
  `tests/contract/test_quality_contract.py` proves the behaviour against a
  throwaway project built from GLOBIN's own settings rather than asserting that
  a string appears in a list. The individual options are used rather than the
  `strict` umbrella, for the same reason `mypy --strict` is avoided in S-05.

### S-02 — pytest: import modes and test package layout

- **Canonical location:** https://docs.pytest.org/en/stable/explanation/pythonpath.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the pytest project documenting its own import
  behaviour.
- **Supports:** pytest supports three import modes, `prepend`, `append` and
  `importlib`. Under `prepend`, the first directory not containing an
  `__init__.py` — the *rootdir* of the test module — is inserted at the front of
  `sys.path`. Under `importlib`, modules are imported without modifying
  `sys.path` at all. `--import-mode` is a command-line option; the reference
  documents no equivalent ini key.
- **Implication for GLOBIN:** this is what made `from conftest import ...` work
  before Phase 4 — `tests/` was inserted into `sys.path` as a side effect of
  containing no `__init__.py`. Organising tests into taxonomy subdirectories
  changes which directory is inserted and breaks every such import. `tests` is
  therefore now a package, shared helpers live in an importable
  `tests/support.py`, and `--import-mode=importlib` is passed through `addopts`
  because no ini key exists for it. Confirmed empirically: declaring `importmode`
  as an ini key was rejected by `--strict-config` with
  `Unknown config option: importmode`.

## Coverage measurement

### S-03 — Coverage.py: branch coverage

- **Canonical location:** https://coverage.readthedocs.io/en/latest/branch.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the Coverage.py project documenting its own
  behaviour.
- **Supports:** branch coverage measures whether each possible transition out of
  a conditional was taken, rather than only whether the conditional line
  executed. A partially-covered branch is reported distinctly from a fully
  covered one.
- **Implication for GLOBIN:** measurement is branch-aware. The architecture
  contract code is composed almost entirely of conditionals over a declared
  policy, so a line-based figure would report a rule whose violating path is
  never exercised as fully tested. That is the precise failure the guard-the-
  checker principle in `../TESTING_STRATEGY.md` exists to prevent.

### S-04 — Coverage.py: configuration, exclusions and the failure threshold

- **Canonical location:** https://coverage.readthedocs.io/en/latest/config.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the Coverage.py project documenting its own
  configuration.
- **Supports:** the `[report]` section documents both `exclude_lines`, which
  **replaces** the default exclusion list, and `exclude_also`, which **adds** to
  it. `fail_under` causes the run to fail when total coverage is below the given
  figure. `source` selects what is measured.
- **Implication for GLOBIN:** `exclude_also` is used, not `exclude_lines`. The
  distinction is easy to get wrong and silent when wrong — the previous
  configuration used `exclude_lines` and had to restate `pragma: no cover`
  manually to recover a default it had discarded. The exclusions added are
  `if TYPE_CHECKING:` bodies and bare `...` bodies; the latter removes the only
  two uncovered lines in `globin.ports`, which are `Protocol` method
  declarations with nothing to execute. `source` covers `globin` and `tools`, so
  the quality runner that decides whether a gate ran is itself measured.

## Static analysis

### S-05 — mypy: configuration file and the contents of strict mode

- **Canonical location:** https://mypy.readthedocs.io/en/stable/config_file.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the mypy project documenting its own configuration.
- **Supports:** mypy is configured under `[tool.mypy]` in `pyproject.toml`.
  `strict` is documented as enabling a set of other flags, and the documentation
  notes that the precise set may change over time as new checks are added.
- **Implication for GLOBIN:** `strict = true` is prohibited and every flag it
  implies is written out. `mypy --help` on the installed version 2.1.0 was read
  directly rather than relying on the prose list, and reports the expansion as
  `--disallow-any-generics`, `--disallow-subclassing-any`,
  `--disallow-untyped-calls`, `--disallow-untyped-defs`,
  `--disallow-incomplete-defs`, `--check-untyped-defs`,
  `--disallow-untyped-decorators`, `--warn-redundant-casts`,
  `--warn-unused-ignores`, `--warn-return-any`, `--no-implicit-reexport`,
  `--strict-equality` and `--extra-checks`. Those thirteen are declared
  explicitly. The documented fact that the set may change is exactly the reason:
  under the alias, a mypy upgrade alters what GLOBIN's type contract means with
  no diff to review. Verified: the suite type-checks clean under the explicit
  list, so it is no weaker than the alias it replaced.

### S-06 — mypy: optional error codes

- **Canonical location:** https://mypy.readthedocs.io/en/stable/error_code_list2.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the mypy project documenting its own error codes.
- **Supports:** this page lists error codes that are **not** enabled by default
  and are switched on with `enable_error_code`. Among them, `ignore-without-code`
  reports a `# type: ignore` comment written without a specific error code in
  square brackets.
- **Implication for GLOBIN:** `ignore-without-code` is enabled, along with
  `redundant-expr`, `truthy-bool`, `truthy-iterable`, `possibly-undefined` and
  `unused-awaitable`. A bare `# type: ignore` silences every error on its line,
  including ones written a year later that nobody has seen; requiring the code
  makes each suppression name the single thing it suppresses. This is the mypy
  half of the same policy Ruff's `PGH` rules enforce for `noqa`.

### S-07 — Ruff: rule selection and configuration

- **Canonical location:** https://docs.astral.sh/ruff/settings/
- **Accessed:** 2026-08-14
- **Authority:** Primary — Astral documenting its own tool.
- **Supports:** rules are selected by prefix through `lint.select`, where a
  prefix may name a whole family. `lint.per-file-ignores` disables specific
  rules for paths matching a pattern. `lint.isort.known-first-party` controls
  which imports are treated as belonging to the project.
- **Implication for GLOBIN:** eleven families were added to the fifteen Phase 001
  selected, chosen against the priority order recorded in
  `../engineering/STATIC_ANALYSIS.md`. `known-first-party` now names `globin`,
  `tests` and `tools`, since all three are imported by name. Only one
  `per-file-ignores` entry exists — `S101` for `tests/**`, because `assert` is
  the assertion mechanism in a test and pytest is never run under `-O`.

### S-08 — Ruff: formatter compatibility with lint rules

- **Canonical location:** https://docs.astral.sh/ruff/formatter/
- **Accessed:** 2026-08-14
- **Authority:** Primary — Astral documenting its own tool.
- **Supports:** certain lint rules conflict with the formatter and are
  recommended to be disabled, including the `Q` quote family, `COM812`,
  `COM819`, and the implicit string concatenation rules `ISC001` and `ISC002`.
  The page states that `E501` may be used alongside the formatter but that
  formatted code can still exceed the line length. Critically, it states that
  **`ruff format` emits a warning when an incompatible lint rule or setting is
  enabled**, and that a warning-free `ruff format` means the configuration is
  compatible.
- **Implication for GLOBIN:** `ISC` is deliberately not selected, and the
  documented warning provides a way to check rather than assume. `ruff format
  --check` over this repository completes with no warnings, which confirms
  empirically that no enabled rule conflicts with the formatter. `E501` is kept,
  since the repository's line-length rule is enforced on documentation as well
  as code.

## Local hooks and continuous integration

### S-09 — pre-commit: configuration and hook pinning

- **Canonical location:** https://pre-commit.com/
- **Accessed:** 2026-08-14
- **Authority:** Primary — the pre-commit project documenting its own behaviour.
- **Supports:** `.pre-commit-config.yaml` declares `repos`, each with a `rev`
  identifying the revision to use and a list of `hooks`. A `repo: local` entry
  runs a command from the project itself; `language: system` uses the
  environment's own interpreter, and `pass_filenames: false` suppresses passing
  matched paths as arguments. Hooks that modify files cause the run to fail and
  leave the modification in the working tree.
- **Implication for GLOBIN:** hook revisions are pinned to released tags, read
  from each project's published `.pre-commit-hooks.yaml` so that hook IDs are
  confirmed rather than guessed. `ruff-pre-commit` is pinned to the same version
  as the Ruff the quality gate and CI run, so the hook and the gate cannot
  return different verdicts. The local hook runs
  `python -m tools.quality architecture` with `pass_filenames: false`. Four
  hooks rewrite files, and `../engineering/QUALITY_GATES.md` names them, because
  a hook that edits silently is indistinguishable from one that failed.
  `mixed-line-ending` is deliberately not used: `.gitattributes` checks Windows
  scripts out as CRLF on purpose.

### S-10 — GitHub Actions: security hardening for workflows

- **Canonical location:** https://docs.github.com/en/actions/reference/security/secure-use
- **Accessed:** 2026-08-14
- **Authority:** Primary — the platform vendor documenting its own product.
- **Supports:** pinning an action to a full-length commit SHA is stated to be
  the most secure option; pinning to a tag is described as more convenient and
  acceptable only where the action's creators are trusted. The page sets out the
  principle of least privilege for the `GITHUB_TOKEN`, noting that any user with
  write access to a repository has read access to all its secrets, and that
  credentials used within workflows should have the least privilege required.
- **Implication for GLOBIN:** every action in `.github/workflows/quality.yml` is
  pinned to a full 40-character commit SHA, each resolved from the GitHub API at
  authoring time and recorded with its release in a trailing comment. The
  workflow declares `permissions: contents: read` at workflow level, references
  no secret at all, and passes `persist-credentials: false` to the checkout. A
  contract test rejects any `uses:` reference that is not a SHA, and asserts the
  absence of secret references.

### S-11 — GitHub Actions: workflow syntax for permissions and triggers

- **Canonical location:** https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
- **Accessed:** 2026-08-14
- **Authority:** Primary — the platform vendor documenting its own product.
- **Supports:** `permissions` may be set at workflow or job level and controls
  the scopes granted to the `GITHUB_TOKEN`; specifying it replaces the default
  rather than adding to it. `on.push.branches` and `on.pull_request.branches`
  filter which refs trigger a run. `concurrency` with `cancel-in-progress`
  supersedes an in-flight run in the same group. `jobs.<id>.continue-on-error`
  allows a job to fail without failing the workflow.
- **Implication for GLOBIN:** `permissions` is declared once at workflow level so
  that a job added later starts read-only rather than inheriting a repository
  default that may be broader. Triggers are limited to `master`, matching the
  master-only workflow (ADR-0005). `continue-on-error` is never used, and a
  contract test asserts its absence — a step that cannot fail the build is
  decoration.

## Packaging metadata

### S-12 — Python Packaging User Guide: the `pyproject.toml` specification

- **Canonical location:** https://packaging.python.org/en/latest/specifications/pyproject-toml/
- **Accessed:** 2026-08-14
- **Authority:** Primary — PyPA, the body publishing the packaging
  specifications.
- **Supports:** `pyproject.toml` carries `[build-system]`, `[project]` and
  arbitrary tool configuration under `[tool.*]`. The `[project]` table's fields,
  including `optional-dependencies`, are specified there; `[tool.*]` tables are
  owned entirely by the named tool.
- **Implication for GLOBIN:** pytest, Ruff, mypy and Coverage.py remain
  configured in `pyproject.toml` and nowhere else, and a contract test rejects a
  committed `setup.cfg`, `tox.ini`, `pytest.ini`, `mypy.ini`, `.flake8` or
  `ruff.toml`. `pre-commit` was added to the `dev` optional-dependency group,
  which required updating the contract test that pins that group's membership —
  deliberate friction, so that a change to the toolchain is a change someone
  reviews.

---

## Facts deliberately left unverified in Phase 4

| Question | Why unresolved | Phase that must resolve it |
|---|---|---|
| Does the CI workflow actually run green? | It has never executed. It is authored, checked by contract tests and reviewed, but its first real run happens on push. | Observed on the next push to `master` |
| Do the pinned tool versions install on both 3.12 and 3.14? | Only Python 3.14.5 exists on this host, so the 3.12 leg of the matrix is untested. | 018, which selects and pins the interpreter |
| Is the dependency set reproducible? | Four `==` pins in a workflow are a reproducibility measure, not a lockfile. | 020, which owns resolution and locking |
| Does the package build and install correctly? | No build has been run; the suite executes from `src/` via `pythonpath`. | 017-032 |
