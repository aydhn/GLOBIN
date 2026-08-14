# Phase 007 — Research Source Ledger

Every external claim made by Phase 7 traces to an entry below. Entries are
summaries written for GLOBIN's purposes; documentation text is not copied into
this repository.

Phase 7 relies on external behaviour in two places: the standard library modules
the configuration model is built from, and the TOML specification the document
format follows. It adds no dependency, and it relies on no exchange behaviour,
because it reaches nothing.

**Ledger conventions**

- `Authority: Primary` means the vendor or upstream project publishing its own
  behaviour. `Secondary` means anything else.
- Several entries record a fact **verified by running the code in this
  repository**, not only by reading it. Where that happened the entry says so.
- Where a fact could not be established from a primary source in this phase, the
  entry says so explicitly and names the phase that must resolve it.
- All accesses were performed on the date recorded in each entry.

---

## The model

### S-01 — Python: `dataclasses.fields` — order and the `MISSING` sentinel

- **Canonical location:** https://docs.python.org/3/library/dataclasses.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the language documenting its own standard library.
- **Supports:** `fields()` returns a tuple of `Field` objects, accepts either a
  dataclass or an instance of one, and raises `TypeError` if given neither. The
  documentation states that the order of the fields in all generated methods is
  the order in which they appear in the class definition. `MISSING` is a sentinel
  used to detect whether a parameter was provided, chosen because `None` is
  itself a valid value with a distinct meaning; a field declaring no default has
  `Field.default` set to it.
- **Implication for GLOBIN:** this is what makes the dataclass the schema rather
  than a restatement of one. `section_keys` and `section_defaults` in
  `src/globin/domain/configuration.py` derive the key register and the defaults
  layer from `fields()`, so a setting cannot exist in one and not the other, and
  the declaration order the documentation guarantees is what makes the register
  stable between runs. A field whose `default` is `MISSING` is refused as an
  `InternalError`, because a setting that cannot resolve without a document makes
  the defaults layer incomplete. Verified by running this repository's suite: a
  synthetic section with an undefaulted field raises, and one with three defaults
  yields them in declaration order.

### S-02 — Python: `dataclasses` — `frozen` and `slots`

- **Canonical location:** https://docs.python.org/3/library/dataclasses.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the language documenting its own standard library.
- **Supports:** `frozen=True` adds `__setattr__` and `__delattr__` methods that
  raise `FrozenInstanceError` when invoked. `slots=True` generates a `__slots__`
  attribute and returns a new class rather than the original, and raises
  `TypeError` if `__slots__` is already defined.
- **Implication for GLOBIN:** the configuration model, every layer and every
  resolved setting are `frozen=True, slots=True`, matching the convention Phases
  003-006 established. Immutability is what lets a configuration be passed
  through the system without any caller needing to know whether someone else
  holds a reference to it, which
  [`ENGINEERING_CONTRACT.md`](../engineering/ENGINEERING_CONTRACT.md) invariant 5
  requires of anything long-lived.

### S-03 — Python: `enum.IntEnum` — ordering, membership and lookup by name

- **Canonical location:** https://docs.python.org/3/library/enum.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the language documenting its own standard library.
- **Supports:** `IntEnum` members compare against one another and against
  integers by value, so `min`, `max` and the ordering operators work on them
  directly. A member is retrieved by name with subscript access, `Severity[name]`.
  Membership is by identity of the member object, not by numeric equality.
- **Implication for GLOBIN:** the severity threshold is a comparison rather than
  a lookup table — the promise `Severity`'s docstring has carried since Phase 006.
  Verified by running this repository's suite: `isinstance(30, Severity)` and
  `isinstance(True, Severity)` are both `False`, which is what makes the refusal
  of a numeric threshold a property of the type rather than a hand-written check,
  and `min(Severity)` is `DEBUG`, which is what makes the default threshold
  provably discard nothing.

---

## The document format

### S-04 — Python: `tomllib` — binary input, and the error a malformed file raises

- **Canonical location:** https://docs.python.org/3/library/tomllib.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the language documenting its own standard library.
- **Supports:** The module provides an interface for parsing TOML 1.0.0. `load()`
  takes a readable and **binary** file object, as its own example shows with
  `open(..., "rb")`. `TOMLDecodeError` is documented as a subclass of
  `ValueError`. The module does not support writing TOML.
- **Implication for GLOBIN:** `TomlConfigurationSource.layer()` opens the
  document with `open("rb")` inside a `with` block — binary because the module
  requires it, and inside a context manager because
  `filterwarnings = ["error"]` turns the `ResourceWarning` from an unclosed file
  into a failure attributed to whichever test happens to run next.
  `TOMLDecodeError` is allowed through unwrapped rather than translated into a
  `ConfigurationError`, matching the treatment
  `TomlArchitectureContractSource` has given it since Phase 003: the line and
  column it reports are worth more to an operator than a reworded message. That
  it subclasses `ValueError` is noted rather than relied upon — GLOBIN's own
  taxonomy inherits from no builtin ([ADR-0022](../adr/0022-error-taxonomy-rooted-in-one-type.md)),
  and this exception is not GLOBIN's. Writing TOML is not supported and is not
  needed: nothing in GLOBIN emits configuration.

### S-05 — TOML v1.0.0 — a quoted key containing a dot is one key

- **Canonical location:** https://toml.io/en/v1.0.0
- **Accessed:** 2026-08-14
- **Authority:** Primary — the specification publishing its own format.
- **Supports:** Quoted keys follow the same rules as basic or literal strings and
  allow a much broader set of key names. A dot inside a quoted key is therefore
  part of the key rather than a separator; the specification's own
  `"site."google.com" = true` example has `google.com` as a single key within the
  `site` table.
- **Implication for GLOBIN:** this is the reason `flatten` in
  `src/globin/adapters/configuration.py` refuses a key containing a dot rather
  than accepting it. GLOBIN's resolved keys are flat and dotted, so `"a.b" = 1`
  and `[a]` with `b = 1` would flatten to the same key while meaning different
  things in the document. There is no answer to that collision which is not a
  guess, so it is refused with a message naming the key and the file. Verified by
  running the parser in this repository: `tomllib.loads('[a]\n"c.d" = 2\n')`
  yields a table whose single key is `c.d`.

### S-06 — TOML v1.0.0 — dotted keys define the tables above them

- **Canonical location:** https://toml.io/en/v1.0.0
- **Accessed:** 2026-08-14
- **Authority:** Primary — the specification publishing its own format.
- **Supports:** Dotted keys are a sequence of bare or quoted keys joined with a
  dot, and they create and define a table for each key part before the last one,
  provided such tables were not previously created.
- **Implication for GLOBIN:** an operator may write either `[logging]` with
  `min_severity = "WARNING"` beneath it, or `logging.min_severity = "WARNING"` at
  the top level, and the specification makes both produce the same nested
  structure before GLOBIN sees it. Flattening therefore needs no special case for
  the two spellings, and `docs/CONFIGURATION_POLICY.md` can state one key per
  setting without also having to state which layout a document must use — a
  question that belongs to Phase 026 in any case.
