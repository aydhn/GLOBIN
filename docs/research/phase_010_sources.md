# Phase 010 — Research Source Ledger

Every external claim made by Phase 10 traces to an entry below. Entries are
summaries written for GLOBIN's purposes; documentation text is not copied into
this repository.

Phase 10 relies on external behaviour in one place: the semantics of the
standard library's `decimal` module. It reaches no venue, adds no dependency and
integrates with nothing. Several of its decisions turn on behaviour that is
documented but easy to misread, so most entries below record a fact **verified
by running the code on this machine** as well as by reading the specification.

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

## The decimal context

### S-01 — Python: arithmetic operators use the thread-local context

- **Canonical location:** https://docs.python.org/3/library/decimal.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the language documenting its own standard library.
- **Supports:** The documentation states that the current context is a
  thread-local, that arithmetic operations use it, and that its default
  precision is 28 significant digits. Rounding that occurs during an operation is
  signalled through `Inexact` and `Rounded`, which are not trapped by default.
  **Verified by running the code in this repository:**
  `Decimal('1E+30') + Decimal('1E-30')` returns
  `1.000000000000000000000000000E+30` — the addend is discarded and no exception
  is raised.
- **Implication for GLOBIN:** This is the failure the phase exists to prevent. It
  is why no module under `src/globin` uses a `Decimal` arithmetic operator on an
  amount, and why `ENGINEERING_CONTRACT.md` invariant 22 is at stake rather than
  merely style.

### S-02 — Python: signals may be trapped, turning a rounding into an exception

- **Canonical location:** https://docs.python.org/3/library/decimal.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** A `Context` carries a `traps` mapping; a trapped signal raises
  rather than returning a substitute value. `Inexact` is signalled whenever a
  result was rounded. **Verified:** a context at `prec=128` with `Inexact`
  trapped returns the exact 61-digit sum of `1E+30` and `1E-30`; the same
  computation at `prec=60` raises `Inexact`.
- **Implication for GLOBIN:** "Exact or refused" is implementable without writing
  any arithmetic. `precision._exact_context` arms `Inexact`, `InvalidOperation`,
  `DivisionByZero`, `Overflow` and `Underflow`, so a result that cannot be given
  exactly is not given at all.

### S-03 — Python: `Context` methods do not touch the thread-local context

- **Canonical location:** https://docs.python.org/3/library/decimal.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** The `Context` object exposes methods mirroring the arithmetic
  operators — `add`, `subtract`, `multiply`, `divmod`, `remainder` — which
  perform the operation using *that* context. **Verified:** after
  `Context(prec=128, ...).add(...)`, `decimal.getcontext()` returns the same
  object as before, with its `prec` unchanged and its `flags` still empty.
- **Implication for GLOBIN:** This is the entry the phase turns on.
  [ADR-0031](../adr/0031-value-types-compare-but-do-not-compute.md) refused exact
  arithmetic in the domain partly because `localcontext` mutates thread-local
  state inside a domain method. That objection is true of `localcontext` and
  false of a `Context` method, so ADR-0037 adopts the design ADR-0031 declined,
  on evidence rather than on argument.

### S-04 — Python: a `Context` accumulates flags, so it is mutable state

- **Canonical location:** https://docs.python.org/3/library/decimal.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** A context's `flags` record which signals have occurred since they
  were last cleared. **Verified:** a fresh `Context(prec=28)` shows
  `['Inexact', 'Rounded']` set after a single `quantize` call.
- **Implication for GLOBIN:** A module-level `Context` constant would be mutable
  global state, which `ENGINEERING_CONTRACT.md` invariant 5 forbids. Together
  with the rule that no layer module may perform a call at import, this is why
  `_exact_context()` is a function that builds a fresh context every time.

### S-05 — Python: constructing a `Context` is cheap

- **Canonical location:** https://docs.python.org/3/library/timeit.html
- **Accessed:** 2026-08-14
- **Authority:** Primary, for the measurement method; the number is this
  machine's.
- **Supports:** **Measured** at roughly **604 ns** per construction over 100 000
  iterations of `Context(prec=128, Emin=-999999, Emax=999999, traps=[Inexact])`
  on CPython 3.14.5, Windows 11.
- **Implication for GLOBIN:** The per-call construction S-04 requires costs
  submicrosecond time, so the guarantee is bought cheaply. This is a
  characteristic of this machine and this interpreter; it is recorded so that a
  later phase profiling a hot path starts from a number rather than a guess.

---

## Alignment onto a grid

### S-06 — Python: `divmod` is exact, and its quotient is an integer

- **Canonical location:** https://docs.python.org/3/library/decimal.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** `Context.divmod` returns the integer part of the quotient and the
  remainder, both computed exactly. **Verified:**
  `divmod(Decimal('60000.123'), Decimal('0.05'))` returns
  `(Decimal('1200002'), Decimal('0.023'))`; the quotient's exponent is `0`, and
  multiplying it back by the step yields exponent `-2` — the step's own.
- **Implication for GLOBIN:** Alignment is implemented with no division at all,
  and the venue's stated precision survives it. An increment of `0.00010000`
  produces aligned values spelled to eight places, which is what
  [ADR-0030](../adr/0030-domain-values-are-denominated-wrappers-over-decimal.md)
  refused a scaled-integer representation in order to preserve.

### S-07 — Python: an oversized quotient is refused, not rounded

- **Canonical location:** https://docs.python.org/3/library/decimal.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** The specification defines `divide-integer` as signalling
  `DivisionImpossible` — a condition of `InvalidOperation` — when the integer
  quotient would have more digits than the context's precision. **Verified:**
  `divmod(Decimal('1E+200000'), Decimal('0.01'))` in a 128-digit context raises
  `InvalidOperation`.
- **Implication for GLOBIN:** The fail-closed behaviour the phase wants is the
  library's own. `precision._divide` translates the signal into a
  `ValidationError` naming the operands and the digit budget, rather than
  catching and continuing.

### S-08 — Python: `Decimal` accepts a `float` and expands it exactly

- **Canonical location:** https://docs.python.org/3/library/decimal.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** Constructing a `Decimal` from a `float` is exact, and therefore
  reproduces the binary approximation in full. **Verified:** `Decimal(0.01)` has
  **58 significant digits**.
- **Implication for GLOBIN:** `Increment` refuses a `float` by type, and the
  `MAX_INCREMENT_DIGITS` bound catches the case where one arrives already
  converted — the same two-layer defence `values.py` uses for an amount, and the
  reason the digit bound is a *bound* rather than advice.

---

## Independent verification

### S-09 — Python: `fractions.Fraction` as an exactness oracle

- **Canonical location:** https://docs.python.org/3/library/fractions.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** `Fraction` implements unbounded exact rational arithmetic and
  constructs losslessly from a `Decimal`. It is part of the standard library and
  shares no implementation with `decimal`.
- **Implication for GLOBIN:** `tests/property/test_precision_properties.py`
  checks every exact operation against the rational answer. Because the two
  implementations are independent, they cannot share a bug — which is the
  property that makes the oracle worth more than recomputing the same result the
  same way. It adds no dependency, so ADR-0003 is untouched.

---

## What this phase did not establish

Nothing in Phase 10 required a Binance source, and none was consulted. The real
tick and step sizes of any market are venue data owned by **Phases 049-050**,
reached through the integration band **033-048**; this phase deliberately
contains no venue constant, and
`tests/integration/test_precision_end_to_end.py` writes its tick and step down as
literals with a comment saying so.

Whether a fee is charged on the notional or on the received quantity, and at what
tier, is **Phase 148**. The fee arithmetic in this phase's tests is shaped like a
fee only to exercise `CEILING`; it asserts nothing about any venue's schedule.
