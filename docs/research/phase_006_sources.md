# Phase 006 — Research Source Ledger

Every external claim made by Phase 6 traces to an entry below. Entries are
summaries written for GLOBIN's purposes; documentation text is not copied into
this repository.

Phase 6 relies on external behaviour in one place: the standard library modules
the logging adapter uses to serialise, stamp and identify a record. It adds no
dependency, and it relies on no exchange behaviour, because it reaches nothing.

**Ledger conventions**

- `Authority: Primary` means the vendor or upstream project publishing its own
  behaviour. `Secondary` means anything else.
- Several entries record a fact **verified by running the code in this
  repository**, not only by reading it. Where that happened the entry says so.
- Where a fact could not be established from a primary source in this phase, the
  entry says so explicitly and names the phase that must resolve it.
- All accesses were performed on the date recorded in each entry.

---

## Serialisation

### S-01 — Python: `json` — non-finite floats

- **Canonical location:** https://docs.python.org/3/library/json.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the language documenting its own standard library.
- **Supports:** The documentation states that the RFC does not permit the
  representation of infinite or NaN number values, and that despite this the
  module by default accepts and outputs `Infinity`, `-Infinity` and `NaN` as
  though they were valid JSON number literals. `allow_nan=False` makes
  serialising an out-of-range float raise `ValueError` instead.
- **Implication for GLOBIN:** neither default is acceptable. Emitting `NaN`
  produces a line that a strict reader rejects, and raising means a logging call
  can fail on a value a calculation produced. `_coerce` in
  `src/globin/adapters/observability.py` therefore converts a non-finite float
  to text before serialisation, so the emitted line is valid JSON and the call
  cannot raise. Verified by running the suite: a property test generates NaN and
  both infinities and asserts the output parses.

### S-02 — Python: `json` — `ensure_ascii` and `separators`

- **Canonical location:** https://docs.python.org/3/library/json.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the language documenting its own standard library.
- **Supports:** `ensure_ascii` defaults to `True`, and when true the output is
  guaranteed to have all incoming non-ASCII and non-printable characters
  escaped. `separators` is a two-tuple `(item_separator, key_separator)`;
  `(",", ":")` produces the most compact output.
- **Implication for GLOBIN:** both are passed explicitly rather than relied on
  as defaults, because the escaping one is load-bearing. GLOBIN's host is
  Windows, where a console stream is frequently not UTF-8, and an ASCII-only
  record can be written whatever encoding the stream has. A default that later
  changed would silently reintroduce `UnicodeEncodeError` on a symbol name.

### S-03 — JSON Lines

- **Canonical location:** https://jsonlines.org/
- **Accessed:** 2026-08-14
- **Authority:** Primary — the specification's own site.
- **Supports:** Each line is a valid JSON value; the line terminator is `\n`; a
  final terminator after the last value is recommended; blank lines are not
  acceptable; a byte order mark must not be included. Log files are named as one
  of the intended use cases. The specification also observes that JSON permits
  encoding Unicode with ASCII escape sequences but that **those escapes are hard
  to read in a text editor**.
- **Implication for GLOBIN:** `StreamLogSink` writes one JSON object per line and
  terminates every line, including the last. The independence of each line is
  what lets a truncated log file still be read and what lets the integration test
  parse output line by line.

  GLOBIN deliberately departs from the readability observation. `ensure_ascii`
  is left at `True`, so non-ASCII is escaped and a symbol or Turkish field value
  is harder to read directly. The reason is S-02: the host is Windows, the
  console stream is frequently not UTF-8, and a record that cannot be written is
  worse than one that is awkward to read. The departure is recorded here rather
  than hidden, and it is reversible in one argument if GLOBIN later writes only
  to files it opens itself with a known encoding.

---

## Time and identity

### S-04 — Python: `datetime` — aware timestamps and ISO 8601 output

- **Canonical location:** https://docs.python.org/3/library/datetime.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the language documenting its own standard library.
- **Supports:** `datetime.now(tz)` returns an aware object when `tz` is given
  and a naive one otherwise. `datetime.UTC` is an alias for `timezone.utc`,
  added in 3.11. `isoformat()` on an aware datetime appends the UTC offset, and
  for UTC that suffix is `+00:00`.
- **Implication for GLOBIN:** the adapter calls `datetime.now(UTC)` and
  `isoformat()`, so every record carries an unambiguous instant. `+00:00` is
  asserted directly in `tests/unit/test_observability.py`, which is what would
  catch a change to a naive clock. The interpreter floor is 3.12, so the
  `datetime.UTC` alias is available.

### S-05 — Python: `uuid` — `uuid4` and `hex`

- **Canonical location:** https://docs.python.org/3/library/uuid.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the language documenting its own standard library.
- **Supports:** `uuid4()` generates a random UUID by a cryptographically secure
  method, per RFC 9562 §5.4. `UUID.hex` is the UUID as a 32-character lowercase
  hexadecimal string.
- **Implication for GLOBIN:** `new_correlation_id` returns `uuid4().hex`, which
  is why the correlation id is safe to embed in JSON without escaping and why
  the unit test asserts a length of 32 and an alphanumeric body. Generation
  reads a randomness source, so it lives in the adapter layer beside the clock.

---

## Record construction

### S-06 — Python: `dataclasses` — `__post_init__`, `frozen` and `slots`

- **Canonical location:** https://docs.python.org/3/library/dataclasses.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the language documenting its own standard library.
- **Supports:** `__post_init__` is called by the generated `__init__` after the
  fields have been initialised. `frozen=True` adds `__setattr__` and
  `__delattr__` that raise `FrozenInstanceError`. The documentation states that
  a frozen dataclass's `__init__` "cannot use simple assignment to initialize
  fields, and must use `object.__setattr__()`". `slots=True` generates
  `__slots__` and returns a new class.
- **Implication for GLOBIN:** `LogEvent` redacts itself in `__post_init__` using
  `object.__setattr__`, which is what makes an unredacted instance
  unconstructible. Note the limit of what the documentation establishes: it
  describes `object.__setattr__` as what the *generated `__init__`* must use, and
  does **not** document the same technique inside `__post_init__`. That the
  extension works on frozen-and-slotted classes was established by running the
  suite against the installed interpreter (3.14.5), not by reading it — see the
  unresolved table below.

### S-07 — Python: `enum` — `IntEnum`

- **Canonical location:** https://docs.python.org/3/library/enum.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the language documenting its own standard library.
- **Supports:** `IntEnum` members are also integers and may be used anywhere an
  integer can, comparing and ordering as their values do. Since Python 3.11
  `__str__` is `int.__str__`, so `str(member)` yields the number rather than the
  member name.
- **Implication for GLOBIN:** `Severity` is an `IntEnum`, so a future threshold
  is a comparison rather than a lookup table. The `__str__` change is the trap:
  serialising with `str(severity)` would have written `20` instead of `INFO` and
  looked correct in a diff. The adapter uses `severity.name`, and
  `tests/unit/test_observability.py` asserts the written value is the name.

### S-08 — Python: `logging` — standard level numbers

- **Canonical location:** https://docs.python.org/3/library/logging.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the language documenting its own standard library.
- **Supports:** The standard levels are `NOTSET` 0, `DEBUG` 10, `INFO` 20,
  `WARNING` 30, `ERROR` 40 and `CRITICAL` 50, and levels should be positive
  integers increasing with severity.
- **Implication for GLOBIN:** `Severity` borrows these five numbers exactly, so
  a sink bridging to the standard library later needs no mapping table between
  two enumerations. GLOBIN does not import `logging` to obtain them — the
  numbers are written out, and this entry is why they are the numbers they are.
  `NOTSET` is deliberately not mirrored: a record with no severity is not a
  thing GLOBIN emits.

---

## Facts deliberately left unverified in Phase 6

| Question | Why unresolved | Phase that must resolve it |
|---|---|---|
| Whether `object.__setattr__` inside `__post_init__` on a frozen, slotted dataclass is a guaranteed behaviour or an implementation detail | The documentation sanctions the technique for the generated `__init__` only. It was confirmed by running the suite on CPython 3.14.5, and CI additionally exercises 3.12, but no primary source states it for `__post_init__`. | 013, when typing and structure conventions are fixed |
| Whether a future runtime dependency emits standard-library log records that GLOBIN should capture | No runtime dependency exists yet, so there is nothing to observe. The port makes a bridging sink an addition rather than a rewrite. | 021-022, at the first runtime dependency |
| Which field names beyond the current list carry secrets | The list is a defensible starting set, not an inventory. No credential exists in this repository to enumerate against. | 015 |
| Where log records should be written, and with what rotation | Sink configuration is configuration, and none exists. Phase 6 ships a stream sink and the composition root chooses `sys.stderr`. | 007 for the model, 026 for the file layout |
| Whether the clock the adapter reads should be injectable | Phase 6 needs a timestamp three phases before the phase that decides how time works. Building a clock port here would pre-empt that decision. | 009 |
