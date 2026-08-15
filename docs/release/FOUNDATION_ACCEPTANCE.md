# Foundation Acceptance — Phases 001-016

This document certifies that the first band of the GLOBIN programme — *Phases
001-016, Repository Foundation and Engineering Contract* — is complete, and
records what each requirement rests on.

It is the prose half of a pair. The machine-readable half is
[`../engineering/foundation-acceptance.toml`](../engineering/foundation-acceptance.toml),
which `python -m tools.quality release` reads and
`tests/contract/test_release_contract.py` compares against this document in both
directions. Neither can drift from the other without failing the suite.

---

## What this certifies, and what it does not

**It certifies** that the foundation the next band builds on exists, is
enforceable, and is answerable: every criterion below names something that can be
opened, read, and re-checked.

**It does not certify** that GLOBIN works, because GLOBIN does not yet do
anything. There is no exchange connection, no credential, no market data, no
strategy and no backtesting. Roadmap rule 6 makes each band end with a
consolidation phase "to pay down inconsistency before the next band builds on top
of it", and that — not readiness to trade — is what is being signed off.

**It is not a test run.** The gate that reads the declaration does not re-execute
fifteen phases of checks. It verifies the mechanical half — no repeated
identifier, no misfiled one, every evidence path present, every category
populated, no blocking criterion unmet. The judgement itself is written down by a
person, in a file that can be reviewed and diffed, exactly as
[`../engineering/mutation-baseline.toml`](../engineering/mutation-baseline.toml)
records a survivor's argument. A gate claiming to re-derive the judgement would
be claiming more than it does.

---

## Status vocabulary

| Status | Meaning |
|---|---|
| `PASS` | Met, with evidence that exists. |
| `FAIL` | Not met. A blocking criterion in this state stops a release. |
| `BLOCKED` | The answer depends on something outside this repository. **Never a pass** — the gate maps it onto the unmeasured verdict, which [ADR-0045](../adr/0045-a-platform-capability-is-a-recorded-state-never-a-pass.md) established outranks a failure. |
| `NOT_APPLICABLE` | Genuinely out of scope, with the reason recorded rather than implied. |

There is deliberately **no `WARN`**. A warning has no release semantics until
somebody writes them down, and the semantics it acquires in practice are "proceed
anyway" — which is the failure this gate exists to prevent.

---

## Result

**54 criteria across sixteen categories. 52 are blocking.**

| Status | Count |
|---|---|
| `PASS` | 53 |
| `FAIL` | 0 |
| `BLOCKED` | 1 |
| `NOT_APPLICABLE` | 0 |

**Every blocking criterion passes.** The single `BLOCKED` criterion is
`FND-P-05`, tag signing, which is non-blocking and is discussed under
[Unresolved](#unresolved) below.

---

## The matrix

Identifiers are `FND-<letter>-<NN>`, where the letter is the category's position:
`A` for the first, `P` for the sixteenth. The identifier and the category say the
same thing twice on purpose — the identifier is what gets quoted in a report
months later, the category is what groups the matrix — and the gate checks that
the two agree.

### A — Repository foundation

| ID | Requirement | Blocking | Status |
|---|---|---|---|
| `FND-A-01` | Project identity is executable rather than merely documented. | yes | `PASS` |
| `FND-A-02` | The 320-phase band structure is fixed and machine-readable. | yes | `PASS` |
| `FND-A-03` | No credential-shaped file and no generated artefact can be committed. | yes | `PASS` |

### B — Engineering contract

| ID | Requirement | Blocking | Status |
|---|---|---|---|
| `FND-B-01` | One document states what all code must satisfy. | yes | `PASS` |
| `FND-B-02` | One document states when a phase is finished, and it is the only copy. | yes | `PASS` |
| `FND-B-03` | Conflicts between documents are resolved by a declared authority order. | yes | `PASS` |
| `FND-B-04` | Every error raised has one root and a category chosen by who must act. | yes | `PASS` |

### C — Architecture boundaries

| ID | Requirement | Blocking | Status |
|---|---|---|---|
| `FND-C-01` | The permitted import directions are declared once, machine-readably. | yes | `PASS` |
| `FND-C-02` | The declared direction is enforced against the real import graph. | yes | `PASS` |
| `FND-C-03` | Dependencies are wired in one composition root, and importing performs no work. | yes | `PASS` |

### D — Decision records

| ID | Requirement | Blocking | Status |
|---|---|---|---|
| `FND-D-01` | Every architectural decision is recorded, indexed and numbered without gaps. | yes | `PASS` |
| `FND-D-02` | A superseded decision is marked as superseded rather than deleted. | yes | `PASS` |

### E — Living documentation

| ID | Requirement | Blocking | Status |
|---|---|---|---|
| `FND-E-01` | Required documents exist, are substantive, and carry no placeholder debt. | yes | `PASS` |
| `FND-E-02` | Every repository-relative Markdown link resolves. | yes | `PASS` |
| `FND-E-03` | A number or table written in prose is compared against its source. | yes | `PASS` |

### F — Static analysis

| ID | Requirement | Blocking | Status |
|---|---|---|---|
| `FND-F-01` | Tool configuration lives in pyproject.toml and nowhere else. | yes | `PASS` |
| `FND-F-02` | Type checking is strict, and the strictness is written out flag by flag. | yes | `PASS` |
| `FND-F-03` | Every lint family selected, and every exemption, has a recorded reason. | yes | `PASS` |

### G — Deterministic tests

| ID | Requirement | Blocking | Status |
|---|---|---|---|
| `FND-G-01` | A test's level is decided by its directory, not by a decorator. | yes | `PASS` |
| `FND-G-02` | The suite is offline by construction, and refuses a socket rather than trusting convention. | yes | `PASS` |
| `FND-G-03` | Invariants are asserted over generated input under a deterministic CI profile. | yes | `PASS` |

### H — Regression controls

| ID | Requirement | Blocking | Status |
|---|---|---|---|
| `FND-H-01` | Branch coverage is measured over the package and the tooling, against a floor. | yes | `PASS` |
| `FND-H-02` | Surviving mutants are recorded with an argument, and compared in both directions. | yes | `PASS` |
| `FND-H-03` | Narrow disciplines are enforced structurally, not by review. | no | `PASS` |

### I — Runtime isolation

| ID | Requirement | Blocking | Status |
|---|---|---|---|
| `FND-I-01` | A test leaves the environment and working directory as it found them. | yes | `PASS` |
| `FND-I-02` | The suite's result is invariant under partitioning into separate processes. | yes | `PASS` |
| `FND-I-03` | Time is an injected clock, and reading it directly is refused. | yes | `PASS` |

### J — Test evidence

| ID | Requirement | Blocking | Status |
|---|---|---|---|
| `FND-J-01` | One run produces machine-readable evidence whose schema version is a contract. | yes | `PASS` |
| `FND-J-02` | Every published evidence file is covered by a checksum manifest. | yes | `PASS` |
| `FND-J-03` | Generated artefacts are scanned for material they must not carry. | yes | `PASS` |

### K — CI aggregation

| ID | Requirement | Blocking | Status |
|---|---|---|---|
| `FND-K-01` | One aggregate check decides a run, and a job that never ran cannot pass it. | yes | `PASS` |
| `FND-K-02` | The jobs a run requires are declared, and compared to the workflow both ways. | yes | `PASS` |

### L — CI hardening

| ID | Requirement | Blocking | Status |
|---|---|---|---|
| `FND-L-01` | Every action is pinned to a full commit SHA and declared in a manifest. | yes | `PASS` |
| `FND-L-02` | The token starts read-only, and a privileged scope is bound to a trigger a fork cannot reach. | yes | `PASS` |
| `FND-L-03` | No repository secret exists, and adding one requires a recorded decision. | yes | `PASS` |

### M — Supply chain

| ID | Requirement | Blocking | Status |
|---|---|---|---|
| `FND-M-01` | Dependencies are inventoried from every register that declares one, and drift is reported. | yes | `PASS` |
| `FND-M-02` | A CycloneDX SBOM is generated here, deterministically. | yes | `PASS` |
| `FND-M-03` | A dependency is adopted through a written review, not a commit. | yes | `PASS` |
| `FND-M-04` | Tracked content is scanned for credentials, and findings never carry the value. | yes | `PASS` |
| `FND-M-05` | A vulnerability is either open or waived with an expiry, judged against the commit date. | yes | `PASS` |

### N — Security governance

| ID | Requirement | Blocking | Status |
|---|---|---|---|
| `FND-N-01` | Ownership and change control are declared once and validated offline. | yes | `PASS` |
| `FND-N-02` | Every security-sensitive path is owned more specifically than by the catch-all. | yes | `PASS` |
| `FND-N-03` | A vulnerability has a private reporting channel and a written response procedure. | yes | `PASS` |
| `FND-N-04` | Where a secret may live is written down, and redaction happens before a record exists. | yes | `PASS` |

### O — Release governance

| ID | Requirement | Blocking | Status |
|---|---|---|---|
| `FND-O-01` | The project version has exactly one source, and the build backend reads it. | yes | `PASS` |
| `FND-O-02` | How a version is chosen, tagged and published is written down in one place. | yes | `PASS` |
| `FND-O-03` | Every released version is announced in a changelog. | yes | `PASS` |
| `FND-O-04` | Automatic release notes are configured, with a catch-all category. | yes | `PASS` |
| `FND-O-05` | A published release tag cannot be moved or deleted. | yes | `PASS` |

### P — Release readiness

| ID | Requirement | Blocking | Status |
|---|---|---|---|
| `FND-P-01` | A deterministic gate checks the release contract before anything is published. | yes | `PASS` |
| `FND-P-02` | Every published asset is covered by a SHA-256 digest. | yes | `PASS` |
| `FND-P-03` | The foundation matrix is readable by a person, not only by the gate. | yes | `PASS` |
| `FND-P-04` | The release is published under immutability, so its tag and assets cannot change. | yes | `PASS` |
| `FND-P-05` | The release tag's cryptographic status is recorded as what it actually is. | no | `BLOCKED` |

---

## Unresolved

### `FND-P-05` — tag signing is unavailable

The development host holds no signing key material: no `user.signingkey`, no
`gpg.format`, no GPG secret key, and no SSH key. This was probed rather than
assumed, and the readings are S-14 in
[`../research/phase_016_sources.md`](../research/phase_016_sources.md).

`v0.1.0` is therefore an **annotated, unsigned** tag. The release manifest
records `ANNOTATED_UNSIGNED`, and no document in this repository describes the
release as signed.

**Why it is not blocking.** No policy here requires a signed release, and the
alternative was worse than the gap. Generating a key so a tag could be labelled
"signed" would produce a signature proving possession of a key created for that
purpose — worth nothing cryptographically, and reading to anybody scanning the
evidence as though it were worth something. A recorded absence is more honest
than a manufactured presence, which is the same argument
[ADR-0045](../adr/0045-a-platform-capability-is-a-recorded-state-never-a-pass.md)
makes about platform capabilities.

**What resolving it needs.** Key material the owner provides, plus a decision
about which backend. It cannot be resolved from inside the repository, which is
what `BLOCKED` means here rather than `FAIL`.

---

## What was reconciled

A consolidation phase is meant to pay down inconsistency. What Phase 016 found
and fixed:

- **`SECURITY.md` asserted something this phase made false.** Its supported-versions
  section stated that GLOBIN "has never been published, tagged, packaged or
  distributed" and that "Versioning and release policy belong to a later phase".
  Both were true when written and neither survived this phase. Rewritten.
- **`docs/GIT_WORKFLOW.md` had no tag or release procedure at all** — a real gap
  once a release exists. It now links to
  [`RELEASE_POLICY.md`](RELEASE_POLICY.md) rather than growing a second copy,
  because [ADR-0011](../adr/0011-documentation-authority-hierarchy.md) makes two
  copies of one rule the defect to avoid.
- **`pyproject.toml`'s header comment named a file that had moved**, citing
  `tests/test_packaging_contract.py` for what is now
  `tests/contract/test_packaging_contract.py`.
- **The delivered-phase frontier** moved to 016 in every place that states it:
  the roadmap banner and its status row, the README, the package docstring, the
  issue-template chooser, and the constant the tests bind them all to.

---

## Phase 017 handoff

Phase 016 closes the first band. **Phase 017 may begin.**

The next band — *Phases 017-032, Environment and Tooling* — owns everything Phase
016 deliberately did not touch:

| Area | Owner |
|---|---|
| Windows host requirements: operating system, hardware, storage, network | Phase 017 |
| Python interpreter selection and pinning, verified against wheel availability | Phase 018 |
| Virtual environment lifecycle: creation, validation, repair, recreation | Phase 019 |
| Dependency resolution and lock files | Phase 020 |
| Runtime configuration bootstrap | Phases 021-032 |
| Credential and secret onboarding — the *store*, not the rules | Phases 021-032 |

Phase 015 wrote the secret-handling rules and built no secret store; that
distinction still holds and is the next band's to close.

**What Phase 017 inherits.** A repository whose rules are executable rather than
advisory, a layered architecture enforced against the real import graph, a suite
that is offline and process-isolated by construction, machine-readable evidence
for every gate, a hardened CI pipeline reduced to one required check, a
supply chain that is inventoried, audited and attested, governance that is
declared once and validated offline, and a version that has one source and a
release that is frozen against change.

**What Phase 017 must not assume.** That a packaging build works — none has been
run, and describing one as verified before Phases 017-032 is specifically
forbidden by [`../../MEMORY.md`](../../MEMORY.md). That a `.venv` exists or is
managed. That any credential exists anywhere. That anything in this repository
has ever contacted Binance.
