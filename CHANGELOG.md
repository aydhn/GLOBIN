# Changelog

Every released version of GLOBIN is announced here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) as
[`docs/release/RELEASE_POLICY.md`](docs/release/RELEASE_POLICY.md) applies it.

**A version appears here exactly once.** `python -m tools.quality release`
refuses a changelog that announces one version under two headings, because a
reader of the second cannot tell which describes the release.

**No dates are invented.** Phases 001-015 were delivered before this file
existed, and their individual commit dates are in the Git history rather than
reconstructed here. The `0.1.0` entry groups what the foundation band produced,
by capability rather than by phase, and every group below names something that
can be opened and read.

---

## [Unreleased]

### Dependency locking

- The development toolchain is locked. `pylock.dev.toml` records all forty-nine
  distributions the seven declared tools resolve to, each with a digest, in the
  PEP 751 format `pip lock` produces. Before this, seven were pinned by the
  workflows and the other forty-two entered an environment at whatever version an
  index served that day.
- **The lock is load-bearing rather than decorative.** `scripts/bootstrap.ps1`
  builds `.venv` from it and pip verifies every digest; an unreadable lock is a
  refusal rather than a silent fall back to the pins, and `-FromPins` restores the
  previous behaviour as a deliberate act.
- **The vulnerability audit changed meaning, not only scope.** It ran against a
  requirements file synthesised from the pins, which `pip-audit` then resolved
  against a live index *at audit time* — so the report described a resolution
  nobody had installed, and two runs on one commit could disagree.
  `pip-audit --locked` resolves nothing, so the audited set is the installed set.
- Every claim the lock makes is **recomputed from the lock's own evidence** by
  `python -m tools.quality lock`, offline: each digest, each artefact host, each
  wheel's PEP 425 tags against the runtime contract, and each version the four
  registers carry. pip wrote the file and labels the feature experimental;
  validating it with pip would establish only that pip agrees with itself.
- `lock installed` compares this environment; `lock relock` and `lock upgrade`
  regenerate the lock and reach the index. A relock holds the workflow pins and
  the producer, so it records the transitive set rather than upgrading the tools
  somebody chose. A regenerated lock that is wrong *about itself* is refused and
  set aside with the committed file untouched; one that merely disagrees with the
  pins is kept, and the exact edits are printed.
- **There is no runtime lock, and that is enforced rather than remembered.**
  `project.dependencies` is empty, and `pip-audit --locked` raises on a lock
  recording no packages — so creating one would break the gate this work
  strengthens. `LOCK_RUNTIME_UNLOCKED` fails the moment a runtime dependency is
  declared without `pylock.toml` beside it, which is Phase 021's to add.
- What the gate cannot check is stated rather than implied: pip records no
  dependency edges, so nothing offline can prove every locked package is reachable
  from a declared root.

### Secret store contract

- [`docs/security/SECRET_STORE_CONTRACT.md`](docs/security/SECRET_STORE_CONTRACT.md)
  records what Windows actually offers a credential store, closing a question
  ADR-0048 left open when it chose the store's properties as capabilities "so that
  Phase 028 can satisfy them with whatever Windows actually offers".
- **No store is implemented and no mechanism is chosen.** The measured limits bind
  Phases 026 to 029: a credential blob has a documented 2560-byte ceiling, a target
  name is case-insensitive and cannot be edited after creation, a write replaces
  with no compare-and-swap, and the protection separates accounts rather than
  processes. No claim of memory erasure is made, because CPython cannot support one.

### Environment drift

- The machine the gates are measured on is now compared against a baseline a
  person accepted, not only against the contract.
  `python -m tools.quality.drift accept` records this host;
  `python -m tools.quality drift` reports what has changed since and writes
  `.globin/drift/drift-manifest.json`. `check` never records a baseline — one that
  recorded whatever it found would certify its own observation.
- **With no accepted baseline the verdict is `unmeasured`, not clean.** A fresh
  clone exits `3`. "Could not look" and "looked and found nothing" are different
  facts and the three-valued verdict vocabulary exists so they never share a
  colour.
- Each way a host can diverge is classified in
  [`docs/engineering/drift-policy.toml`](docs/engineering/drift-policy.toml), and
  every recorded repair verdict is recomputed from the action declared beside it:
  an entry claiming a fault is repairable in place whose own declaration does not
  support that fails offline.
- **`drift` fails where `runtime` correctly passes.** The contract declares a
  patch floor, so an interpreter that went *backwards* satisfies it; a
  `PIP_INDEX_URL` or a machine-wide `pip.ini` appearing violates nothing at all.
  Those are changes somebody made to the machine, and they were previously
  invisible.
- **Repair short of recreating the environment now exists, for one fault.**
  `RUNTIME_BASELINE.md` answered five distinct `.venv` faults with "rebuild with
  `-Recreate`"; four of them need it. `pyvenv.cfg` is read at interpreter
  start-up, so `python -m tools.quality.drift repair` corrects
  `include-system-site-packages` by rewriting one key. Everything else names what
  a person should run, or something outside the repository this tooling may not
  touch.
- Reasoning:
  [ADR-0053](docs/adr/0053-drift-is-measured-against-an-accepted-baseline-and-repair-is-a-classification.md),
  and [`docs/engineering/ENVIRONMENT_DRIFT.md`](docs/engineering/ENVIRONMENT_DRIFT.md)
  for what to do about each finding.

### Documentation and secret hygiene

- A policy document may no longer defer a question to a phase that has already
  answered it. Four rows did — in the configuration, identifier, precision and
  value-type policies — telling a reader a question was open, and pointing at the
  wrong number. The convention for recording a met deferral already existed in two
  of the same tables and had simply not been applied; a contract test now compares
  every such row against `ROADMAP.md` in both directions.
- A fifth secret-hygiene control: a committed `.toml`, `.json` or `.yaml` naming a
  key `api_key`, `password`, `token` or similar is refused, whatever its value.
  The filename tripwire does not see it, and the content scanner matches issuer
  grammars rather than key names. The register is reused rather than restated.

### Wheel availability

- The libraries the roadmap schedules are surveyed against the pinned interpreter
  in [`docs/engineering/wheel-survey.toml`](docs/engineering/wheel-survey.toml),
  recording for each the version read, its published `Requires-Python` and the
  wheel filenames the index offers. `python -m tools.quality wheels` recomputes
  every recorded verdict from those filenames offline and writes
  `.globin/wheels/wheel-manifest.json`; `python -m tools.quality.wheels probe`
  asks the index whether the record is still true.
- **Every scheduled library has a wheel for CPython 3.14 on `win_amd64`**, so the
  runtime contract is unchanged. Reasoning and the three findings are in
  [`docs/engineering/WHEEL_AVAILABILITY.md`](docs/engineering/WHEEL_AVAILABILITY.md).
- A gap is recorded and owned rather than treated as a failure: a verdict of
  `source-only` or `absent` must name the phase answering for it, and only an
  unowned gap fails the gate.
- Nothing is resolved, locked or adopted. `project.dependencies` is still empty
  and dependency resolution remains Phase 020's.

### Runtime baseline

- The supported Windows host, CPython and project environment are declared in
  [`docs/engineering/runtime-contract.toml`](docs/engineering/runtime-contract.toml)
  and checked against the machine by `python -m tools.quality runtime`, which
  writes `.globin/runtime/runtime-manifest.json`.
- `scripts/bootstrap.ps1` builds `.venv` from a verified interpreter and installs
  the toolchain the workflows already pin; `scripts/preflight.ps1` diagnoses a
  host and changes nothing.
- `scripts/verify.ps1` now runs under `.venv\Scripts\python.exe` and refuses to
  run without it, so which interpreter measured a result is recorded rather than
  decided by `PATH` order. No automation depends on activation.
- Every path outside the repository is recorded in the evidence as a fingerprint
  rather than a path, and `pip` configuration is recorded as which scopes exist —
  never a value.
- A `Runtime baseline` job builds the environment on a clean Windows runner with
  the same script a developer runs.
- Reasoning:
  [ADR-0050](docs/adr/0050-the-runtime-is-a-declared-contract-and-venv-is-its-only-environment.md),
  and [ADR-0051](docs/adr/0051-phase-017-absorbs-interpreter-pinning-and-the-environment-lifecycle.md)
  for the roadmap amendment it required.

---

## [0.1.0] - 2026-08-15

The foundation baseline: the first version of GLOBIN, closing Phases 001-016.

**This release does not trade.** It has no exchange connection, no credentials,
no market data, no strategy and no backtesting. What it contains is the
repository, the rules every later phase obeys, and the verification backbone that
makes those rules enforceable rather than merely written down. Anything that
talks to an exchange belongs to Phase 033 and beyond.

### Repository and engineering foundation

- Project identity, the master-only branch rule and the exchange scope, encoded
  in `globin.project_contract` and asserted rather than documented.
- The fixed 320-phase programme as twenty bands of sixteen, in `globin.roadmap`.
- The engineering contract, definition of done, documentation standard,
  repository layout and an explicit nine-tier authority order for resolving
  conflicts between documents.
- One error taxonomy: a single root, five categories chosen by who must act, and
  no inheritance from builtins.

### Architecture

- Five layers — domain, ports, application, adapters, runtime — with
  dependencies pointing inward, declared machine-readably in
  `docs/architecture/dependency-rules.toml` and enforced against the real import
  graph read from the AST.
- One composition root, and no work performed at import time.
- Domain value types over `Decimal`: exact arithmetic or refusal, rounding always
  an argument, an injected clock behind two ports, and identifiers that register
  kinds rather than instances.
- Forty-nine architecture decision records, indexed, with superseded decisions
  kept rather than deleted.

### Tests and quality

- Six test levels decided by directory, with markers applied by a collection
  hook so the layout and the selection cannot disagree.
- Offline by construction: an autouse fixture refuses outbound sockets, and a
  second restores the environment and working directory a test changed.
- Property-based testing under two Hypothesis profiles, the CI one derandomised.
- Branch coverage over both the package and the tooling, against a floor of 95.
- Mutation testing as a repository-native harness, gated by a committed survivor
  set whose every entry carries a written argument.
- Deterministic sharded execution, proving the suite's result is invariant under
  partitioning into separate processes.

### Continuous integration

- One command table defines every check, and the local gate, the pre-commit hook
  and CI all read it — so they cannot drift.
- One aggregate check decides a run, and a required job that never started is
  recorded as unmeasured rather than passing by omission.
- Machine-readable test evidence with a versioned, self-digesting manifest and a
  checksum file, carrying no wall clock and no absolute path.

### Supply chain and security

- Dependency inventory across the three registers that declare a dependency,
  with drift reported rather than reconciled silently.
- A deterministic CycloneDX 1.7 SBOM generated in-repository, built twice and
  byte-compared on every run.
- Vulnerability audit with an expiring waiver register judged against the commit
  date, and a credential scanner reporting digests rather than values.
- Every GitHub Action pinned to a full commit SHA, declared in a manifest and
  compared against the workflows in both directions.
- A read-only token by default, no repository secrets, and no privileged
  triggers a fork could reach.

### Repository governance

- Code ownership declared once and validated offline, with every
  security-sensitive path owned more specifically than by the catch-all.
- A private vulnerability reporting channel, a written response runbook, and
  public issue templates that do not solicit exploit detail.
- Secret-handling rules: a secret lives outside the tree and is redacted before a
  record of it exists.

### Release governance

- A single-source project version, read by the build backend from the same file
  that defines it.
- This changelog, a release policy, and the Phase 001-016 foundation acceptance
  matrix in both prose and machine-readable form.
- A release gate that checks the contract deterministically, publishes evidence
  as release assets and covers every asset with a SHA-256 digest.
- Tag protection against deletion and movement, and release immutability enabled
  before this release was published.

### Known limitations

- **The release tag is annotated and unsigned.** This host holds no signing key
  material, and none was manufactured to satisfy a checklist. Recorded as
  `FND-P-05` in the acceptance matrix.
- **No packaging build has been run.** `pyproject.toml` declares a distribution
  and Hatchling can read its version, but no wheel or source distribution has
  been produced or verified. That belongs to Phases 017-032.

[Unreleased]: https://github.com/aydhn/GLOBIN/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/aydhn/GLOBIN/releases/tag/v0.1.0
