# Phase 008 — Research Source Ledger

Every external claim made by Phase 8 traces to an entry below. Entries are
summaries written for GLOBIN's purposes; documentation text is not copied into
this repository.

Phase 8 relies on external behaviour in three places: the `decimal` module the
value types are built from, the `ast` and `subprocess` modules the mutation
harness is built from, and the two third-party mutation testing tools that were
evaluated and not adopted. It adds no dependency, and it relies on no exchange
behaviour, because it reaches nothing.

**Ledger conventions**

- `Authority: Primary` means the vendor or upstream project publishing its own
  behaviour. `Secondary` means anything else.
- Several entries record a fact **verified by running the code on this machine**
  (CPython 3.14.5, Windows), not only by reading it. Where that happened the
  entry says so, and gives the observed value.
- Where a fact could not be established from a primary source in this phase, the
  entry says so explicitly and names the phase that must resolve it.
- All accesses were performed on the date recorded in each entry.

---

## The value types

### S-01 — Python: `decimal` special values and how they compare

- **Canonical location:** https://docs.python.org/3/library/decimal.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the language documenting its own standard library.
- **Supports:** `Decimal` accepts `NaN`, `sNaN`, `Infinity` and `Inf` as input,
  case-insensitively, and constructing one raises nothing. A test for equality
  where either operand is a NaN always returns `False`, including
  `Decimal('NaN') == Decimal('NaN')`, and a test for inequality always returns
  `True`. An attempt to compare two decimals with `<`, `<=`, `>` or `>=` raises
  the `InvalidOperation` signal if either operand is a NaN.
- **Implication for GLOBIN:** this is why `Price` and `Quantity` refuse a
  non-finite amount at construction. A value type that admitted `NaN` would raise
  a `decimal` exception out of an ordinary comparison — not a `globin.errors`
  type, which [ADR-0022](../adr/0022-error-taxonomy-rooted-in-one-type.md)
  requires — and would compare unequal to itself, which no value should.
  Refusing at construction turns the hazard into a `ValidationError` at the point
  where the origin of the bad value is still known.

### S-02 — Python: where `decimal` arithmetic consults the context, and where it does not

- **Canonical location:** https://docs.python.org/3/library/decimal.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** the significance of a new `Decimal` is determined solely by the
  number of digits input; context precision and rounding "only come into play
  during arithmetic operations". `adjusted()`, `as_tuple()`, `is_finite()`,
  `is_signed()` and the other `is_*` predicates are documented as unaffected by
  context.
- **Implication for GLOBIN:** the split between what Phase 8 permits and what it
  defers. Arithmetic reads a thread-local context and may round without saying
  so, which is `ENGINEERING_CONTRACT.md` invariant 22's silent data loss and
  invariant 5's hidden global state at once; comparison does not. So the value
  types order and compare but do not compute, and the rounding policy stays with
  Phase 010. **Verified by running the code in this repository:**
  `Decimal('1E+30') + Decimal('1E-30')` returns
  `1.000000000000000000000000000E+30` — the addend is discarded, silently —
  while two thirty-one digit values compare correctly under `prec=3`. A second
  run of the whole suite under `prec=3, Emin=-5, Emax=5` accepted and refused
  exactly the same values as the default context, which is what "context-free
  refusal" means here.

### S-03 — Python: `Decimal` construction from a `float` is exact and surprising

- **Canonical location:** https://docs.python.org/3/library/decimal.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** if the value is a `float`, the binary floating-point value is
  losslessly converted to its exact decimal equivalent, which "can often require
  53 or more digits of precision"; the documentation gives
  `Decimal(float('1.1'))` as `1.100000000000000088817841970012523233890533447265625`.
- **Implication for GLOBIN:** the factories refuse a `float` outright, which is
  invariant 17 enforced rather than stated. The conversion is not lossy, which is
  what makes it dangerous — it is exact and wrong. **Verified by running the code
  in this repository:** `Decimal(1.1)` carries fifty-two significant digits, so
  it is also caught by `MAX_SIGNIFICANT_DIGITS` when it arrives already typed and
  the `float` guard cannot see it.

### S-04 — Python: `bool` is an `int`, and `Decimal(True)` is one

- **Canonical location:** https://docs.python.org/3/library/functions.html#bool
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** `bool` is a subclass of `int`, so `isinstance(True, int)` is
  `True`.
- **Implication for GLOBIN:** the `bool` guard in the amount factory has to come
  *before* the `int` guard, or `quantity(True, "BTC")` silently becomes a
  quantity of one. **Verified by running the code in this repository:**
  `Decimal(True)` is `Decimal('1')`, and the refusal is asserted by a named unit
  test rather than left to the ordering being remembered.

### S-05 — Python: negative zero is signed and equal to zero

- **Canonical location:** https://docs.python.org/3/library/decimal.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** `is_signed()` returns `True` if the argument has a negative sign,
  and notes that zeros and NaNs can both carry signs.
- **Implication for GLOBIN:** the non-negativity check is `is_signed()` and not
  `< 0`. **Verified by running the code in this repository:**
  `Decimal('-0').is_signed()` is `True` while `Decimal('-0') == 0` is also
  `True`, so a comparison would admit a value that renders as `-0`.

### S-06 — Python: `dataclasses` with `frozen` and `slots`

- **Canonical location:** https://docs.python.org/3/library/dataclasses.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** `frozen=True` makes assigning to a field raise
  `FrozenInstanceError`; `eq=True` (the default) generates `__eq__` comparing the
  fields as a tuple and returning `NotImplemented` for a different class;
  combining `eq=True` with `frozen=True` generates `__hash__`.
- **Implication for GLOBIN:** the generated `__eq__` is what lets equality across
  types answer `False` without any code, while ordering is written by hand so it
  can refuse a unit mismatch. It is also why the `slots=True` mutants recorded in
  `mutation-baseline.toml` observe nothing: hashing and equality read the
  declared fields either way.

### S-07 — Python: `enum.StrEnum`

- **Canonical location:** https://docs.python.org/3/library/enum.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** `StrEnum` members are also instances of `str` and compare equal
  to their values.
- **Implication for GLOBIN:** `Side` follows the precedent `FaultDomain` and
  `Layer` already set. The consequence — `Side.BUY == "BUY"` is `True` — is
  accepted and written down in `VALUE_TYPES_POLICY.md` rather than discovered,
  because it is the one place these types are less strict than the others.

---

## The mutation harness

### S-08 — Python: what `ast.unparse` guarantees, and what it does not

- **Canonical location:** https://docs.python.org/3/library/ast.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** `ast.unparse` produces a string that would yield an equivalent
  tree if parsed back, but "will not necessarily be equal to the original code".
  Comments and formatting are not preserved. `lineno`, `col_offset`,
  `end_lineno` and `end_col_offset` are defined on `ast.expr` and `ast.stmt`
  subclasses, with the end positions optional. The module introduction states
  that "the abstract syntax itself might change with each Python release".
- **Implication for GLOBIN:** three design rules. A mutant's location is captured
  from the original tree *before* unparsing, because unparsing reflows the
  module. Unparsed output is executed once in a throwaway directory and never
  written back into the repository. And because the grammar is version-dependent,
  the CI mutation job runs on one interpreter and a baseline is evidence about
  that interpreter. **Verified by running the code in this repository:**
  `unparse(parse(unparse(t)))` equals `unparse(t)` for all twenty-seven modules
  under `src/` and `tools/`, and every one of the fifty-two mutants of
  `domain/values.py` parses and differs from the original by exactly one line.

### S-09 — pytest: exit codes

- **Canonical location:** https://docs.pytest.org/en/stable/reference/exit-codes.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the project documenting its own behaviour.
- **Supports:** `0` all tests passed, `1` some tests failed, `2` interrupted,
  `3` internal error, `4` command line usage error, `5` no tests were collected,
  `6` maximum number of warnings exceeded.
- **Implication for GLOBIN:** only `0` and `1` are verdicts about a mutant.
  Reading "not zero" as "killed" would score a run that collected nothing as
  perfect, which is why `5` and every other code stop the run as unmeasured
  rather than being counted. **Verified by running the code in this repository:**
  a non-matching `-k` expression and an unregistered marker both exit `5`, while
  a non-existent path exits `4`.

### S-10 — pytest: where the `pythonpath` ini setting inserts its entries

- **Canonical location:** the installed pytest 9.0.3,
  `_pytest/config/__init__.py`, `Config._configure_python_path`
- **Accessed:** 2026-08-14
- **Authority:** Primary — the implementation of the pinned version, read
  directly because the published reference does not state the insertion point.
- **Supports:** the method iterates `reversed(self.getini("pythonpath"))` and
  calls `sys.path.insert(0, str(path))` for each, with the option declared as
  `type="paths"` and therefore resolved against the rootdir. Its own comment
  reads that `pythonpath = a b` will set `sys.path` to `[a, b, x, y, z, ...]`.
- **Implication for GLOBIN:** the single decision the harness is shaped around.
  Because these entries land at `sys.path[0]` after interpreter start-up, they
  win over anything `PYTHONPATH` contributes — so a harness that wrote a mutant
  elsewhere and adjusted `PYTHONPATH` would import the real module every time and
  report every mutant as surviving. The sandbox therefore owns a copy of
  `pyproject.toml` and the child runs with its working directory inside it. The
  canary run checks this on every invocation rather than trusting it.

### S-11 — Python: bytecode caching is keyed on a whole-second timestamp

- **Canonical location:** https://docs.python.org/3/reference/import.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** a source-based cached bytecode file records the source's
  modification time and size and is invalidated when either differs.
- **Implication for GLOBIN:** the harness sets `PYTHONDONTWRITEBYTECODE=1` in the
  child and excludes `__pycache__` from the sandbox copy. Most mutations here
  preserve byte length exactly — `>=` to `>`, `and` to `or`, `True` to `False` in
  a keyword — so two mutants written within the same second could otherwise be
  matched by one cache entry, and the resulting wrong verdict would be silent and
  intermittent. **Not reproduced**, because doing so would require racing the
  clock deliberately; the mechanism is asserted from the specification and the
  mitigation is unconditional and free.

---

## Tools evaluated and not adopted

### S-12 — mutmut requires `fork`, and therefore WSL on Windows

- **Canonical location:** https://github.com/boxed/mutmut — `README.rst`, and
  `src/mutmut/__main__.py`
- **Accessed:** 2026-08-14
- **Authority:** Primary — the project's own documentation and source.
- **Supports:** the README states under *Requirements* that mutmut must be run on
  a system with `fork` support, and that running on Windows means running inside
  WSL. `src/mutmut/__main__.py` calls `os.fork()`, which does not exist on
  Windows. The GitHub Actions matrix in `.github/workflows/tests.yml` is
  `ubuntu-latest` only, across Python 3.10 to 3.14. Issues #404 and #397, both
  asking for Windows support, were open on the date of access.
- **Implication for GLOBIN:** mutmut cannot run on the platform this project
  declares ([ADR-0009](../adr/0009-windows-bat-launchers-as-entry-points.md)) or
  in its continuous integration, which `MEMORY.md` records as Windows-only and
  settled. Version 3.7.0 is otherwise current, supports Python 3.14, and would
  have been the obvious choice.

### S-13 — cosmic-ray is cross-platform but brings thirteen dependencies

- **Canonical location:** https://pypi.org/project/cosmic-ray/ and
  https://github.com/sixty-north/cosmic-ray
- **Accessed:** 2026-08-14
- **Authority:** Primary — the project's own distribution metadata and
  repository.
- **Supports:** version 8.7.0 declares `Operating System :: OS Independent` and
  `requires-python >=3.9`, with classifiers up to Python 3.13 and none for 3.14.
  Its `requires_dist` names thirteen runtime dependencies: `aiohttp`, `anybadge`,
  `attrs`, `click`, `decorator`, `exit-codes`, `gitpython`, `parso`, `rich`,
  `sqlalchemy`, `stevedore`, `toml` and `yattag`. Its CI matrix is
  `ubuntu-latest` across Python 3.9 to 3.13.
- **Implication for GLOBIN:** adopting it would put an HTTP client into the
  development environment of a repository whose suite installs a guard against
  outbound sockets, and would add thirteen names to a toolchain a contract test
  pins at six. Reviewing a dependency for licence, maintenance health and
  supply-chain risk is Phase 014's process, which has not happened. Barred by
  condition 3 of
  [ADR-0032](../adr/0032-verification-tooling-may-be-added-outside-phase-scope.md).

### S-14 — the remaining Python mutation testing tools are unmaintained

- **Canonical location:** https://pypi.org/project/mutatest/ and
  https://pypi.org/project/mutpy/
- **Accessed:** 2026-08-14
- **Authority:** Primary — distribution metadata.
- **Supports:** `mutatest` 3.1.0 declares support for Python 3.7 and 3.8 only;
  `mutpy` 0.6.1 declares 3.4 to 3.7.
- **Implication for GLOBIN:** neither is a candidate on an interpreter floor of
  3.12. Recorded so that the build-or-adopt decision in
  [ADR-0033](../adr/0033-mutation-testing-is-a-repository-native-ast-harness.md)
  can be seen to have considered the field rather than two entries from it.
