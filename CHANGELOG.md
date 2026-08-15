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
