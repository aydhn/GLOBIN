# Phase 019 — Source Ledger

Environment Drift Detection and Repair; what a virtual environment reads at
start-up, what it cannot survive, and which of the two decides whether a fault is
repairable.

Every claim Phase 019 makes about an external system is recorded here, per
[`../SOURCE_POLICY.md`](../SOURCE_POLICY.md).

This phase reads rather than probes. It reaches no index and no network at all,
and the only external systems it makes claims about are CPython's own start-up
behaviour and the `venv` module's documented limits. Those two claims are
load-bearing in a way this ledger should make plain: **they are the entire
difference between `repair` and `recreate`.** Getting either wrong would mean
either destroying an environment that did not need it, or editing a file that
nothing reads and reporting a repair that never happened.

---

## What decides whether a fault is repairable

### S-01 — `pyvenv.cfg` is scanned when the interpreter launches

- **Canonical location:** PEP 405, *Python Virtual Environments* —
  `https://peps.python.org/pep-0405/`
- **Accessed:** 2026-08-16
- **Authority:** Primary — the specification that introduced the file.
- **Supports:** "If a `pyvenv.cfg` file is found either adjacent to the Python
  executable or one directory above it (if the executable is a symlink, it is not
  dereferenced), this file is scanned for lines of the form `key = value`." And of
  the flag: "If the `pyvenv.cfg` file also contains a key
  `include-system-site-packages` with a value of `true` (not case sensitive), the
  `site` module will also add the system site directories to `sys.path` after the
  virtual environment site directories."
- **Implication for GLOBIN:** The flag is read **at start-up**, on every run,
  rather than being baked into the environment when it is created. That is what
  makes `environment.system_site_packages` repairable in place: rewriting one key
  takes effect the next time the interpreter starts, so destroying and rebuilding
  the environment to change it is a remedy out of all proportion to the fault.
  This is the single source that
  [`../engineering/drift-policy.toml`](../engineering/drift-policy.toml) relies on
  for its only `in-place` verdict.

### S-02 — The `site` module re-reads the flag under a virtual environment

- **Canonical location:** Python documentation, `site` — *Module contents* —
  `https://docs.python.org/3/library/site.html`
- **Accessed:** 2026-08-16
- **Authority:** Primary — the documentation of the module that performs it.
- **Supports:** "When running under a virtual environment, the `pyvenv.cfg` file
  in `sys.prefix` is checked for site-specific configurations. If the
  `include-system-site-packages` key exists and is set to `true` (case-insensitive),
  the system-level prefixes will be searched for site-packages, otherwise they
  won't." The page also records that in version 3.14 "`site` is no longer
  responsible for updating `sys.prefix` and `sys.exec_prefix` on Virtual
  Environments. This is now done during the path initialization."
- **Implication for GLOBIN:** A second, independent statement of S-01, from the
  implementation's own documentation rather than from the specification — which
  matters because the phase's only mutating action rests on it. The 3.14 note is
  recorded because 3.14 is the contracted minor line: the responsibility moved
  earlier in start-up, and the flag is still read there, so the repair holds on the
  interpreter this repository actually pins. The case-insensitivity is why the
  repair matches the key case-insensitively and writes it back in one spelling.

---

## What decides that a fault is *not* repairable

### S-03 — A virtual environment is not movable or copyable

- **Canonical location:** Python documentation, `venv` — *Creating virtual
  environments* — `https://docs.python.org/3/library/venv.html`
- **Accessed:** 2026-08-16
- **Authority:** Primary — the documentation of the module that creates them.
- **Supports:** Virtual environments are "Not considered as movable or copyable –
  you just recreate the same environment in the target location." And: "Because
  scripts installed in environments should not expect the environment to be
  activated, their shebang lines contain the absolute paths to their environment's
  interpreters. Because of this, environments are inherently non-portable, in the
  general case… If for any reason you need to move the environment to a new
  location, you should recreate it at the desired location and delete the one at
  the old location."
- **Implication for GLOBIN:** `environment.location.*` is classified `recreate`
  rather than `in-place`, and the classification is documented rather than assumed.
  It also explains why the fault is worth detecting at all: the failure is quiet —
  the interpreter still starts, and only the console scripts misbehave — so nothing
  announces it at the time.

### S-04 — `--system-site-packages` is what sets the flag in the first place

- **Canonical location:** Python documentation, `venv` — *Creating virtual
  environments* — `https://docs.python.org/3/library/venv.html`
- **Accessed:** 2026-08-16
- **Authority:** Primary.
- **Supports:** Of `--system-site-packages`: "Give the virtual environment access
  to the system site-packages directory." And: "The created `pyvenv.cfg` file also
  includes the `include-system-site-packages` key, set to `true` if `venv` is run
  with the `--system-site-packages` option, `false` otherwise."
- **Implication for GLOBIN:** The observation and the contract are talking about
  the same thing. `runtime-contract.toml` declares `system_site_packages = false`,
  the environment records the answer in `pyvenv.cfg`, and this is the documented
  correspondence between the two — so the drift gate reads the same key Phase 017
  checks rather than inferring the setting from behaviour.

---

## Why nothing generates the declaration

### S-05 — The standard library reads TOML and does not write it

- **Canonical location:** Python documentation, `tomllib` —
  `https://docs.python.org/3/library/tomllib.html`
- **Accessed:** 2026-08-16
- **Authority:** Primary.
- **Supports:** "This module does not support writing TOML." The module provides
  `load` and `loads` only, and raises `TOMLDecodeError`, which "is a subclass of
  `ValueError`", on invalid input. The page points elsewhere for a writer: "Tomli-W
  is a write-only counterpart to Tomli" and "TOML Kit… can be used to edit TOML
  files while preserving style."
- **Implication for GLOBIN:** `drift-policy.toml` carries a "NOT A SNAPSHOT"
  banner, and the tooling physically cannot refresh it — the same position
  `mutation-baseline.toml` records about itself. A contract test asserts that
  neither `tomli_w` nor `toml.dump` appears anywhere in the package, so the
  refusal is enforced rather than merely intended. The error type is why a
  malformed policy is reported as unmeasured with the line and column intact
  rather than reworded.

---

## What was not consulted, and why

**No Binance documentation.** Phase 019 is about this machine. Nothing in it
reaches an exchange, and nothing in it decides anything about one.

**No package index.** The drift gate reaches no network at all: both halves of its
comparison are on the host. The toolchain versions it reads come from metadata
already installed, through `importlib.metadata`, and the versions it compares them
against are already declared in this repository. Phase 018's `wheels probe` is the
gate that asks an index a question, and it remains the only one.

**No claim about how Windows stores its own state.** The gate records that a pip
configuration file exists at a documented scope and that a `PIP_*` variable is
set, by name. It reads neither. Anything further would be a claim about a
credential store, which is Phase 028's, and reading a value in order to report
that a value exists is the mistake that would make this evidence unpublishable.
