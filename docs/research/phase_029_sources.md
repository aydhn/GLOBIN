# Phase 029 — Source Ledger

Every external claim Phase 029 relied on, where it was read, and what GLOBIN does
differently because of it. The rules this ledger follows are in
[`../SOURCE_POLICY.md`](../SOURCE_POLICY.md).

This phase has two halves and the ledger reflects both: the credential flow that
`ROADMAP.md` row 029 asks for, and the dependency attestation delivered as the
thirteenth scope amendment.

Entries marked **Probe** were measured on this host rather than read. Each records
what was run and what it answered — and four of them **changed an implementation
decision**, which is said in bold where it happened. Two of those four contradicted
something this phase had already written, which is the reason the probes exist.

---

### S-01 — PEP 751 requires a tool to refuse a lock whose major version it does not implement

- **Canonical location:** Python Packaging Authority, *pylock.toml Specification* — `https://packaging.python.org/en/latest/specifications/pylock-toml/`
- **Accessed:** 2026-08-18
- **Authority:** Primary — the specification itself, published by the body that owns the format.
- **Supports:** "If a tool doesn't support a major version, it MUST raise an error." And, for the companion case: "If a tool supports the major version but not the minor version, a tool SHOULD warn when an unknown key is seen."
- **Implication for GLOBIN:** The two clauses are implemented as two different states rather than one. `LockState.UNSUPPORTED` refuses and reaches `CheckStatus.FAIL`; `LockState.NEWER_MINOR` warns and reaches `CheckStatus.WARN`, which `exit_code_for` ignores. Collapsing them would have made a lock written by a newer pip refuse a start-up that the specification says should merely be warned about.

### S-02 — The canonical file name is fixed by a pattern, and GLOBIN's locks already match it

- **Canonical location:** Python Packaging Authority, *pylock.toml Specification* — `https://packaging.python.org/en/latest/specifications/pylock-toml/`
- **Accessed:** 2026-08-18
- **Authority:** Primary.
- **Supports:** The specification fixes the file name as `pylock.toml` or `pylock.<name>.toml`, matching `^pylock\.([^.]+\.)?toml$`.
- **Implication for GLOBIN:** **This changed the framing of the phase.** The brief described `pylock.toml` as an *interoperability* format to be supported alongside a different canonical lock. It is not: `pylock.toml` and `pylock.dev.toml` are already canonical PEP 751 names, adopted at Phase 020. There was no interoperability layer to build, and the residue was elsewhere.

### S-03 — Every hashed source requires at least one digest, and the sources are mutually exclusive

- **Canonical location:** Python Packaging Authority, *pylock.toml Specification* — `https://packaging.python.org/en/latest/specifications/pylock-toml/`
- **Accessed:** 2026-08-18
- **Authority:** Primary.
- **Supports:** The `hashes` table "MUST contain at least one entry"; "at least one secure algorithm from `hashlib.algorithms_guaranteed` SHOULD always be included (at time of writing, `sha256` specifically is recommended)". The five source forms — `vcs`, `directory`, `archive`, `sdist`, `wheels` — are mutually exclusive, and a `vcs` entry requires `commit-id`.
- **Implication for GLOBIN:** The immutability rule the brief asks for — no floating VCS branches — is enforced by the *format*, not only by policy, so nothing was written to check it. `tools/quality/materialize` refuses `md5`, `sha1` and `sha224` by name regardless of what any policy file permits, which is stricter than the SHOULD.

### S-04 — `packaging.pylock` is a complete, documented, non-provisional PEP 751 implementation

- **Canonical location:** Python Packaging Authority, *packaging* documentation, `pylock` module — `https://packaging.pypa.io/en/stable/pylock.html`
- **Accessed:** 2026-08-18
- **Authority:** Primary — the reference implementation's own documentation.
- **Supports:** The module is documented public API, "Added in version 26.0"; `select()` was "Added in version 26.1" and extended in 26.3. `Pylock.from_dict` is documented as "Create and validate a Pylock instance from a TOML dictionary", raising `PylockValidationError` when the input is not spec-compliant. Nothing in the page marks it provisional or experimental.
- **Implication for GLOBIN:** **This changed a decision.** The plan for this phase was to hand-write a second PEP 751 reader for the runtime, because `src/globin` cannot import `tools/`. It does not: `read_lock` is a thin translation of `Pylock.from_dict` into bounded states. The consequence is that the two-reader tripwire now checks the delivered Phase 020 parser against the *reference implementation*, rather than pinning two hand-written readers to each other.

### S-05 — pip's hash-checking mode is global, and excludes three algorithms by name

- **Canonical location:** pip documentation, *Secure installs* — `https://pip.pypa.io/en/stable/topics/secure-installs/`
- **Accessed:** 2026-08-18
- **Authority:** Primary — the installer's own documentation.
- **Supports:** "Specifying `--hash` against _any_ requirement will activate this mode globally." "The recommended hash algorithm at the moment is sha256, but stronger ones are allowed… However, weaker ones such as md5, sha1, and sha224 are excluded to avoid giving a false sense of security." "Hashes are required for _all_ dependencies."
- **Implication for GLOBIN:** `WEAK_ALGORITHMS` in `tools/quality/materialize/plan.py` refuses exactly those three, matching both pip and the existing lock gate rather than choosing independently. The all-or-nothing property is why an artefact with no usable digest is `UNHASHED` — a state distinct from missing — instead of being quietly skipped.

### S-06 — `pip lock` and `pip install -r pylock.toml` are both marked experimental

- **Canonical location:** pip documentation, *pip lock* — `https://pip.pypa.io/en/stable/cli/pip_lock/`
- **Accessed:** 2026-08-18
- **Authority:** Primary.
- **Supports:** The command is headed "EXPERIMENTAL - Lock packages and their dependencies from:", and the `--requirement` option records that "pylock.toml support is experimental".
- **Implication for GLOBIN:** Nothing changed, and that is the finding. `docs/engineering/lock-policy.toml` already records `experimental = true` against the producer and carries it into the manifest, so the hedge was already visible in the evidence. This phase did not build on `pip lock`; it reads the lock pip produced.

### S-07 — Probe: this host's `getpass` warns *before* it reads, so aborting is possible

- **Canonical location:** CPython standard library source, `Lib/getpass.py`, read as installed on this
  host. Upstream: `https://github.com/python/cpython/blob/main/Lib/getpass.py`
- **Accessed:** 2026-08-18
- **Authority:** Primary — the implementation that will actually run.
- **Supports:** `fallback_getpass` calls `warnings.warn('Can not control echo on the terminal.', GetPassWarning, stacklevel=2)` **before** it prints its notice and **before** it calls `_raw_input`.
- **Implication for GLOBIN:** **This changed a decision.** `SECRET_STORE_CONTRACT.md` section 5 requires the warning to abort collection. Reading the ordering showed the abort can be made to happen before the operator types anything, so `ConsoleSecretEntry._read` converts the warning to an error and the value **never exists** rather than existing and being discarded. That is stronger than the contract asks for, and it is only possible because of where the `warn` call sits.

### S-08 — Probe: `win_getpass` ignores the stream it is handed

- **Canonical location:** CPython standard library source, `Lib/getpass.py`, read as installed on this
  host. Upstream: `https://github.com/python/cpython/blob/main/Lib/getpass.py`
- **Accessed:** 2026-08-18
- **Authority:** Primary.
- **Supports:** `win_getpass` writes its prompt with `msvcrt.putwch` character by character, and never touches the `stream` argument. It also begins `if sys.stdin is not sys.__stdin__: return fallback_getpass(prompt, stream)`.
- **Implication for GLOBIN:** Two consequences, both recorded rather than worked around. The prompt reaches the console rather than the injected stream on Windows — it never reaches standard output, so the `--json` contract holds, but the stream injection is not the guarantee it appears to be. And because pytest always replaces `sys.stdin`, the echo-suppressed read cannot be exercised under the suite on Windows at all, which is why it is one line behind a seam and why every test here covers a refusal.

### S-09 — Probe: `/dev/null` under Git Bash on Windows reports itself as a terminal

- **Canonical location:** Measured on this host: `.venv\Scripts\python.exe -c "import sys;
  print(sys.stdin.isatty())" < /dev/null`. What the call is documented to mean:
  `https://docs.python.org/3/library/io.html#io.IOBase.isatty`
- **Accessed:** 2026-08-18
- **Authority:** Primary — the behaviour of the shell this repository is developed in.
- **Supports:** The command prints `True` with `/dev/null` redirected, and `False` when standard input is a real pipe.
- **Implication for GLOBIN:** No code changed; a verification method did. The non-interactive refusal cannot be demonstrated by redirecting from `/dev/null` in this environment, because the MSYS emulation of that device still answers `isatty()` truthfully-for-a-console. The refusal was verified with a genuine pipe instead, and the unit tests substitute the stream rather than relying on either.

### S-10 — Probe: `packaging` declares no dependencies and is already in both locks

- **Canonical location:** Installed distribution metadata,
  `.venv\Lib\site-packages\packaging-26.3.dist-info\METADATA`, and the two committed locks.
  The field's meaning: `https://packaging.python.org/en/latest/specifications/core-metadata/`
- **Accessed:** 2026-08-18
- **Authority:** Primary — the artefact that will be installed.
- **Supports:** The metadata carries **zero** `Requires-Dist` lines and `Requires-Python: >=3.9`. Both committed locks already record `packaging` at 26.3, arriving as a transitive of `ta-lib` → `build` since Phase 025.
- **Implication for GLOBIN:** The transitive cost of adopting it as a declared root is nothing, and the lock needed no regeneration — `python -m tools.quality lock` passed with no relock, which is what confirmed the prediction. It is the only entry in `dependency-reviews.toml` whose adoption changes no resolved set.

### S-11 — `packaging` is dual-licensed, and the register's first `OR` expression

- **Canonical location:** *packaging* repository, `LICENSE` — `https://github.com/pypa/packaging/blob/main/LICENSE`
- **Accessed:** 2026-08-18
- **Authority:** Primary — the project's own licence text, not a summary site.
- **Supports:** The file is a dual-licence notice stating the software is made available under the terms of *either* of the licences found in `LICENSE.APACHE` or `LICENSE.BSD`; both files ship inside the distribution, and the metadata declares `License-Expression: Apache-2.0 OR BSD-2-Clause`.
- **Implication for GLOBIN:** `docs/DEPENDENCY_POLICY.md` had already ruled that an `OR` expression "is a choice, and choosing is a decision somebody has to make and record rather than a lookup; the first one that appears gets its own paragraph in this section". This is that first one. The register records the expression whole; the document records the choice — **Apache-2.0**, for the patent grant.

### S-12 — Probe: `pytest` itself requires `packaging`, which is why importing it is safe in CI

- **Canonical location:** Installed distribution metadata,
  `.venv\Lib\site-packages\pytest-9.0.3.dist-info\METADATA`. Upstream declaration:
  `https://github.com/pytest-dev/pytest/blob/main/pyproject.toml`
- **Accessed:** 2026-08-18
- **Authority:** Primary.
- **Supports:** `Requires-Dist: packaging>=22`.
- **Implication for GLOBIN:** This is why `packaging` needs no absent-safe factory, unlike every other runtime dependency: it is present in every CI job that installs pytest, and in `supply` via `pip-audit`. **Availability by circumstance was then converted into a declaration** — `.github/workflows/quality.yml` pins `packaging==26.3` in all five suite-running jobs, so the lock gate's register check now enforces that the pin tracks the lock.

### S-13 — Probe: `packaging` 26.0 and 26.3 do not validate a lock equally strictly

- **Canonical location:** Measured on this host by running one test under `.venv` (packaging 26.3)
  and a bare 3.12 interpreter (packaging 26.0). The validator concerned:
  `https://packaging.pypa.io/en/stable/pylock.html`
- **Accessed:** 2026-08-18
- **Authority:** Primary.
- **Supports:** A lock whose wheel filename names a different distribution from its `[[packages]].name` is refused by 26.3 and accepted by 26.0. Both refuse a name that is not PEP 503-normalised.
- **Implication for GLOBIN:** **This changed a decision, and deleted a test.** A test asserting the filename check was written, passed here, and failed on the bare 3.12 interpreter. It was asserting the *library's* version-specific strictness rather than any behaviour of GLOBIN's, so it was removed and the reason recorded in the file. The normalised-name assertion was kept, because that rule has been in the specification from the start.

### S-14 — Probe: `packaging.tags.Tag` is not orderable, and PEP 425 order is preference

- **Canonical location:** Measured on this host: `sorted(tags)` over a set of `Tag` objects raises
  `TypeError: '<' not supported between instances of 'Tag' and 'Tag'`. The type:
  `https://packaging.pypa.io/en/stable/tags.html`
- **Accessed:** 2026-08-18
- **Authority:** Primary.
- **Supports:** `Tag` defines no ordering. `Pylock.select` takes a `Sequence[Tag]`, and the first tag an artefact matches is the artefact chosen.
- **Implication for GLOBIN:** **This changed a decision.** The declared target was first modelled as a `frozenset[Tag]`, which does not typecheck and, more importantly, was wrong: tag order *is* preference, so an unordered collection asks `select` to choose without saying what "better" means. `declared_target` now returns an ordered tuple, most specific first, with the stable-ABI tags descending. The library declining to invent an ordering is what made the error visible.

### S-15 — Probe: `Pylock.select` is all-or-nothing

- **Canonical location:** Measured on this host against a lock carrying one Linux-only wheel. The
  method: `https://packaging.pypa.io/en/stable/pylock.html`
- **Accessed:** 2026-08-18
- **Authority:** Primary.
- **Supports:** `select` raises `No wheel found matching the provided tags for package 'linux-only' at packages[0], and no sdist available as a fallback` rather than yielding the remaining packages and omitting that one.
- **Implication for GLOBIN:** A single unservable distribution is reported as a lock-level problem naming that package, not as one incompatible entry among many. `PlanState.INCOMPATIBLE` is therefore reachable through the pure planning API and not through the gate. That is defensible for a gate — an environment that cannot be fully built is not partly buildable — and it is recorded here so the next reader does not assume the per-package behaviour that was originally designed for.

### S-16 — Exchange credential formats are read, and deliberately not chosen from

- **Canonical location:** Binance Developer Documentation, *API Key Types* — `https://developers.binance.com/docs/binance-spot-api-docs/faqs/api_key_types`
- **Accessed:** 2026-08-18 (recorded previously as `phase_020_sources.md` S-15 and S-16)
- **Authority:** Primary — the venue's own documentation.
- **Supports:** The venue documents several key types with different shapes and different permitted operations.
- **Implication for GLOBIN:** **Nothing here is implemented, and the omission is the decision.** `entry_problems` validates structure only — non-empty, no surrounding whitespace, no control characters, within the measured store ceiling — and applies no venue-specific format rule. Which key type is used against which surface is Phase 038's, and what a venue says a key may do is Phase 039's. Inventing a length or an alphabet here would be choosing from a register this phase has not read carefully enough to choose from.
