# Phase 032 — Source Ledger

What this phase relied on that it did not measure itself, recorded under
[`../SOURCE_POLICY.md`](../SOURCE_POLICY.md).

**This is the shortest ledger in the programme, and that is a property of the
phase rather than an omission.** A band-closing consolidation phase asks questions
about *this repository* — is a document stale, does a claim hold, was the band
drawn at the right granularity — and those are answered by reading the tree rather
than by consulting anybody. The provisioning half asks two questions about the
outside world, and they are S-01 and S-02 below.

**Four entries changed an implementation decision**, and each says so.

**This ledger overturns no ADR.** It confirms two: ADR-0075's reading of the
Windows architecture APIs, and ADR-0054's account of what `pip` labels
experimental.

---

### S-01 — `subprocess.run` with a list argument and `shell=False` does not involve a shell on Windows

- **Canonical location:** Python Software Foundation, *subprocess — Subprocess management* — `https://docs.python.org/3/library/subprocess.html`
- **Accessed:** 2026-08-19
- **Authority:** Primary — the standard library's own reference for the module GLOBIN uses.
- **Supports:** The documentation states that when `shell` is false the program to execute is specified by the first item of the args sequence, and that on Windows the sequence is converted to a string using the rules the MS C runtime applies. It separately warns that `shell=True` can be a security hazard when combined with untrusted input.
- **Implication for GLOBIN:** **This changed a decision.** `CommandRequest` was going to carry a `shell: bool = False` field for symmetry with the standard library. It carries no such field at all: a caller cannot ask for a shell because the type cannot describe one, which is a stronger guarantee than a default. The adapter passes `shell=False` explicitly anyway, so the two spellings agree.

### S-02 — `subprocess` terminates only the direct child on timeout

- **Canonical location:** Python Software Foundation, *subprocess — Subprocess management*, `subprocess.run` and `TimeoutExpired` — `https://docs.python.org/3/library/subprocess.html#subprocess.run`
- **Accessed:** 2026-08-19
- **Authority:** Primary.
- **Supports:** `run` kills the child on timeout and then waits for it; the documentation describes the behaviour in terms of the child process it started, and does not claim anything about processes that child may itself have started.
- **Implication for GLOBIN:** **This changed a decision.** `BoundedProcessRunner`'s docstring states plainly that the timeout ends the direct child only, and that a grandchild — `pip`, in the one case that would have mattered — is the child's own to clean up. The alternative was a docstring claiming a guarantee the platform does not give.

### S-03 — Keep a Changelog requires one heading per released version

- **Canonical location:** Olivier Lacan, *Keep a Changelog 1.1.0* — `https://keepachangelog.com/en/1.1.0/`
- **Accessed:** 2026-08-19
- **Authority:** Primary — the specification `CHANGELOG.md` declares it follows.
- **Supports:** The format specifies an `Unreleased` section at the top and one section per version below it, newest first, each with its release date.
- **Implication for GLOBIN:** The `0.2.0` cut moves the accumulated `[Unreleased]` entries under a dated heading and opens a fresh `[Unreleased]` above it. `python -m tools.quality release` already refuses a changelog announcing one version twice, so the rule is enforced rather than remembered.

### S-04 — Semantic Versioning permits a minor bump for any backwards-compatible addition, and says nothing constrains `0.y.z`

- **Canonical location:** Tom Preston-Werner, *Semantic Versioning 2.0.0*, clauses 4 and 7 — `https://semver.org/spec/v2.0.0.html`
- **Accessed:** 2026-08-19
- **Authority:** Primary — the specification `RELEASE_POLICY.md` declares it applies.
- **Supports:** Clause 4 states that major version zero is for initial development and that anything may change at any time, with the public API not to be considered stable. Clause 7 states that minor version is incremented when new, backwards-compatible functionality is introduced.
- **Implication for GLOBIN:** `0.2.0` rather than `0.16.0`. `RELEASE_POLICY.md`'s sentence *"each phase that delivers capability increments MINOR"* had never been applied literally — fifteen capability-delivering phases accumulated under one `[Unreleased]` heading — and clause 4 is why that was never wrong. The policy is tightened to say what was actually done: a release is cut at a band boundary, and its minor reflects the capability added since the previous release.

### S-05 — Hatchling builds a wheel from `pyproject.toml` without a setup step

- **Canonical location:** Ofek Lev, *Hatch — Build configuration* — `https://hatch.pypa.io/latest/config/build/`
- **Accessed:** 2026-08-19
- **Authority:** Primary — upstream documentation for the build backend `pyproject.toml` declares.
- **Supports:** The documentation describes the wheel target's default file selection and the `packages` option that narrows it.
- **Implication for GLOBIN:** **This changed a decision.** The provisioning executor was going to invoke `tools.quality.runtime` as a child process to build an environment. The wheel this backend produces contains `globin/` and its `.dist-info` and nothing else — verified by building and opening it, recorded as `ENV-C-04` — so an installed GLOBIN has no `tools/` to invoke. An action now declares its performer, and what GLOBIN cannot do is reported with the command that can.

### S-06 — `pip` labels its lock and its lock-install experimental

- **Canonical location:** Python Packaging Authority, *pip documentation* — `https://pip.pypa.io/en/stable/cli/pip_install/`
- **Accessed:** 2026-08-19
- **Authority:** Primary.
- **Supports:** Both `pip lock` and installing from a PEP 751 lock are documented as experimental features whose behaviour may change.
- **Implication for GLOBIN:** Confirms rather than changes ADR-0054. The environment matrix records it under `ENV-C-01` as the reason the lock gate recomputes every claim from the lock's own contents rather than asking `pip` whether the lock is correct — which would establish only that `pip` agrees with itself.

---

## Deferred, and to where

| Question | Phase |
|---|---|
| Whether ADR-0021's amendment test should be replaced | 048 |
| Whether the runtime substrate deserves roadmap rows of its own | 048 |
| Locking the build backend so a packaging build can be gated offline | 048 |
| Installing a Python runtime from within GLOBIN | 291 |
| Collecting configuration an operator has not supplied | 291 |
| Provisioning a credential without an operator at a console | 292 |
| Whether the network is reachable, measured rather than declared | 045 |
| Refusing a live start on connectivity | 297 |
| Whether a CUDA workload benefits, measured on a device | 183 |
