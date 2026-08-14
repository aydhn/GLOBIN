# Phase 011 — Research Source Ledger

Every external claim made by Phase 11 traces to an entry below. Entries are
summaries written for GLOBIN's purposes; documentation text is not copied into
this repository.

Phase 11 relies on external behaviour in three places: the shape of the value
`uuid.uuid4().hex` produces, the character set RFC 3986 calls unreserved, and
the equality and hashing semantics of a frozen dataclass. It reaches no venue,
adds no dependency and integrates with nothing. **No Binance source is cited,
and that is the point:** this phase fixes what GLOBIN calls things among its own
components. What Binance calls them, and what it will accept in a request, is
Phases 033-048 to establish against primary documentation.

**Ledger conventions**

- `Authority: Primary` means the vendor or upstream project publishing its own
  behaviour. `Secondary` means anything else.
- Several entries record a fact **verified by running the code on this machine**
  (CPython 3.14.5, Windows 11), not only by reading it. Where that happened the
  entry says so, and gives the observed value.
- Where a fact could not be established from a primary source in this phase, the
  entry says so explicitly and names the phase that must resolve it.
- All accesses were performed on the date recorded in each entry.

---

## Identifier generation

### S-01 — Python: `uuid4` produces a randomly generated UUID

- **Canonical location:** https://docs.python.org/3/library/uuid.html
- **Accessed:** 2026-08-15
- **Authority:** Primary — the language documenting its own standard library.
- **Supports:** The documentation describes `uuid.uuid4()` as generating a random
  UUID, in contrast with `uuid1()`, which is built from the host address and a
  timestamp. **Verified by running the code on this machine:** 2000 successive
  calls produced 2000 distinct values.
- **Implication for GLOBIN:** `new_run_id` uses `uuid4` rather than `uuid1`
  because `uuid1` embeds the MAC address of the machine that produced it, which
  would put host identity into every run identifier and therefore into every
  log line and every uploaded evidence artefact. That is the kind of leak
  `docs/SOURCE_POLICY.md` and the redaction rules exist to prevent, and it would
  be invisible.

### S-02 — Python: `UUID.hex` is thirty-two lowercase hexadecimal characters

- **Canonical location:** https://docs.python.org/3/library/uuid.html
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** `UUID.hex` is documented as the UUID as a 32-character
  lowercase hexadecimal string — the `str()` form without its four hyphens.
  **Verified:** across 2000 generated values the length was always 32 and the
  union of characters used was exactly `0123456789abcdef`, with no uppercase
  character observed.
- **Implication for GLOBIN:** `RUN_ID_LENGTH` is 32 exactly rather than a range,
  and `HEX_ALPHABET` is lowercase only. Accepting uppercase as well would make
  one run appear to be two whenever something upstream changed case, which is a
  silent double-count rather than an error. The bound is exact because the kind
  has exactly one producer, so anything of another length did not come from it.

---

## Characters that survive transport

### S-03 — RFC 3986: the unreserved character set

- **Canonical location:** https://www.rfc-editor.org/rfc/rfc3986
- **Accessed:** 2026-08-15
- **Authority:** Primary — the standard defining URI syntax.
- **Supports:** Section 2.3 defines the unreserved characters as the ASCII
  letters, the digits, and the four marks `-`, `.`, `_` and `~`. Characters in
  that set need no percent-encoding anywhere in a URI, and normalisers are
  required to decode any percent-encoded octet that represents one.
- **Implication for GLOBIN:** `OPAQUE_ALPHABET` is that set minus the tilde and
  the full stop. **Verified:** the constant equals the RFC's set with those two
  removed. The tilde is dropped because it is the member most often mangled by
  intermediaries and the least useful in a name; the full stop is dropped
  because it separates levels in `NAME_ALPHABET`, and one character meaning two
  things across two kinds is the ambiguity this phase exists to remove. What a
  venue will actually accept in an order identifier is narrower and is **Phases
  033-048** to establish — nothing here claims to know it.

---

## Value semantics the registry relies on

### S-04 — Python: a frozen dataclass compares by class and fields, and hashes

- **Canonical location:** https://docs.python.org/3/library/dataclasses.html
- **Accessed:** 2026-08-15
- **Authority:** Primary.
- **Supports:** With `eq=True`, which is the default, the generated `__eq__`
  compares the two instances' fields as tuples **and returns `NotImplemented` if
  the other object is not of the same class**. With `frozen=True` as well, a
  `__hash__` is generated, so instances are usable in sets and as mapping keys.
  Assigning to a field of a frozen instance raises
  `dataclasses.FrozenInstanceError`.
- **Implication for GLOBIN:** This is what makes one type per kind worth the
  five classes. `ProductId("spot") == EnvironmentId("spot")` is `False` rather
  than `True`, without a single line of code in either class saying so, because
  the generated comparison refuses across classes. A single `Identifier` type
  carrying a `kind` field would have compared them equal unless somebody
  remembered to compare the kind — and that is the confusion Phase 008 built
  types to prevent. The generated hash is what lets an identifier be a grouping
  key, which is the operation a canonical form exists to make safe.
