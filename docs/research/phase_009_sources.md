# Phase 009 — Research Source Ledger

Every external claim made by Phase 9 traces to an entry below. Entries are
summaries written for GLOBIN's purposes; documentation text is not copied into
this repository.

Phase 9 relies on external behaviour in two places: the standard library modules
the clock is built from, and the venue's published timestamp convention — which
justifies a *convention*, not an integration. It adds no dependency, and it
reaches nothing.

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

## The Python clock surface

### S-01 — Python: `datetime.UTC`, and the deprecation of `utcnow`

- **Canonical location:** https://docs.python.org/3/library/datetime.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the language documenting its own standard library.
- **Supports:** `datetime.UTC` was added in 3.11 as an alias for
  `datetime.timezone.utc`. Both `datetime.utcnow()` and
  `datetime.utcfromtimestamp()` are deprecated since 3.12, and the documented
  replacements are `datetime.now(UTC)` and `datetime.fromtimestamp(ts, UTC)`.
  The stated rationale is that naive datetimes are treated by many `datetime`
  methods as local times, so aware datetimes are preferred for representing UTC.
- **Implication for GLOBIN:** `SystemClock.now` uses `datetime.now(UTC)`, and
  the deprecated spellings appear in the forbidden set that
  `tests/architecture/test_clock_discipline.py` enforces. The deprecation is not
  merely stylistic here: `pyproject.toml` sets `filterwarnings = ["error"]`, so
  reaching for `utcnow()` anywhere in this repository fails the suite rather
  than warning. `utcnow()` returning a *naive* datetime holding UTC is exactly
  the shape `ENGINEERING_CONTRACT.md` invariant 25 forbids from crossing a
  boundary.

### S-02 — Python: aware versus naive objects, and the exact test

- **Canonical location:** https://docs.python.org/3/library/datetime.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** an object is aware when `d.tzinfo is not None and
  d.tzinfo.utcoffset(d) is not None`. Both halves are required: a `tzinfo` whose
  `utcoffset` returns `None` leaves the object naive. `date` objects are always
  naive; a `datetime` may be either.
- **Implication for GLOBIN:** the refusal in `Instant.__post_init__` tests the
  offset rather than merely the presence of a `tzinfo`, because the second half
  of that condition is the one a hand-written check omits. `datetime` is also a
  *subclass* of `date`, so the type check is written against `datetime` — a
  check against `date` would silently admit a `datetime` while a bare `date` has
  no time of day to be an instant of.

### S-03 — Python: `datetime` resolution, and what `utcoffset` may raise

- **Canonical location:** https://docs.python.org/3/library/datetime.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** `datetime.resolution` is `timedelta(microseconds=1)`.
  `utcoffset()` raises `TypeError` if the `tzinfo` returns something other than
  `None` or a `timedelta`, and `ValueError` if the offset is not strictly
  between `-timedelta(hours=24)` and `timedelta(hours=24)`. **Verified by
  running the code on this machine:** a `tzinfo` returning `'nope'` raised
  `TypeError: tzinfo.utcoffset() must return None or timedelta, not 'str'`, and
  one returning `timedelta(days=2)` raised the corresponding `ValueError`.
- **Implication for GLOBIN:** a `tzinfo` is arbitrary caller-supplied code, so
  asking a datetime for its offset is a call into a stranger's implementation
  rather than a field read. Both exceptions are translated into
  `ValidationError`, because [ADR-0022](../adr/0022-error-taxonomy-rooted-in-one-type.md)
  requires that a fault leaving a boundary is a `globin.errors` type. Microsecond
  resolution is why the millisecond conversion is lossy at all.

### S-04 — Python: `astimezone` can leave the representable range

- **Canonical location:** https://docs.python.org/3/library/datetime.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** `datetime` represents years 1 through 9999, and converting an
  aware datetime to another zone shifts it by the offset. **Verified by running
  the code on this machine:** `datetime(1, 1, 1,
  tzinfo=timezone(timedelta(hours=14))).astimezone(UTC)` raised `OverflowError:
  date value out of range`.
- **Implication for GLOBIN:** the `instant()` factory wraps that `OverflowError`
  into a `ValidationError` naming the moment and the reason. It is far from any
  realistic input, which is precisely why it needed finding deliberately rather
  than being waited for — it is reachable only within a day of either end of the
  calendar, and the property strategies leave that day clear so the case is
  tested once, on purpose, rather than generated into every law.

### S-05 — Python: integer conversion from a `timedelta`, and why not `timestamp()`

- **Canonical location:** https://docs.python.org/3/library/datetime.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** `timedelta` normalises itself into days, seconds and
  microseconds, all integers. `datetime.timestamp()` returns a `float`.
  **Verified by running the code on this machine:** for
  `datetime(9999, 12, 31, 23, 59, 59, 999999, tzinfo=UTC)` the exact microsecond
  count computed from the `timedelta` fields is `253402300799999999`, while the
  same value routed through `timestamp()` yields `253402300800000000` — one
  microsecond into a moment that does not exist. The error runs in both
  directions: a 2286 value came back one microsecond short.
- **Implication for GLOBIN:** `Instant.epoch_millis` computes the microsecond
  count from the `timedelta`'s three fields and never through `timestamp()`.
  `MICROSECONDS_PER_DAY` exists for that arithmetic, and its docstring carries
  the measured figures so the choice is not re-litigated as premature caution.

### S-06 — Python: `time.monotonic` and its undefined reference point

- **Canonical location:** https://docs.python.org/3/library/time.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** `monotonic()` returns "the value (in fractional seconds) of a
  monotonic clock, i.e. a clock that cannot go backwards", which "is not
  affected by system clock updates", and whose "reference point of the returned
  value is undefined, so that only the difference between the results of two
  calls is valid".
- **Implication for GLOBIN:** this is the entire justification for
  `MonotonicReading` being a type that cannot be rendered as a time and cannot
  produce epoch milliseconds. Offering either would claim a correspondence the
  platform explicitly declines to make. It is also why the type admits a
  negative reading: a sign rule would be a claim the source does not support.

### S-07 — Python: `time.time` can go backwards

- **Canonical location:** https://docs.python.org/3/library/time.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** "While this function normally returns non-decreasing values, it
  can return a lower value than a previous call if the system clock has been set
  back between the two calls."
- **Implication for GLOBIN:** the reason `Instant` defines no subtraction, and
  the reason wall time and monotonic time are two ports rather than one. An
  elapsed interval measured with the wall clock is correct until an operator or
  an NTP correction steps it mid-measurement, and the resulting defect is a
  quietly wrong number rather than an exception.

### S-08 — Python: `perf_counter`, and why the guarantee was chosen over the resolution

- **Canonical location:** https://docs.python.org/3/library/time.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** `perf_counter()` is "a clock with the highest available
  resolution to measure a short duration", and "does include time elapsed during
  sleep". The `_ns` variants of all these functions exist to "avoid the
  precision loss caused by the float type". **Verified by running the code on
  this machine:** `time.get_clock_info` reports
  `implementation='QueryPerformanceCounter()'`, `monotonic=True`,
  `adjustable=False`, `resolution=1e-07` for **both** `monotonic` and
  `perf_counter`, and `implementation='GetSystemTimePreciseAsFileTime()'`,
  `monotonic=False`, `adjustable=True`, `resolution=1e-07` for `time`.
- **Implication for GLOBIN:** `SystemMonotonicClock` uses `monotonic_ns()`. On
  this host the two counters are the same source, so the choice costs nothing
  measurable and is made purely on which guarantee is documented — the right
  basis, because the declared host is not the only machine this will ever run
  on. `adjustable=True` on the wall clock is the concrete, measured evidence for
  S-07's consequence. The `_ns` note is why `Duration` counts nanoseconds as an
  `int` rather than seconds as a `float`.

### S-09 — Ruff: the `flake8-datetimez` (DTZ) family

- **Canonical location:** https://docs.astral.sh/ruff/rules/
- **Accessed:** 2026-08-14
- **Authority:** Primary — the linter documenting its own rules.
- **Supports:** the `DTZ` family flags naive constructions —
  `datetime()` without `tzinfo`, `datetime.now()` without `tz`, `utcnow()`,
  `utcfromtimestamp()`, `date.today()`, `fromtimestamp()` without `tz`, and
  `strptime` without `%z`. **No DTZ rule flags `time.time()`,
  `time.monotonic()` or `time.perf_counter()`**, and none constrains *where* a
  call may appear.
- **Implication for GLOBIN:** `DTZ` has been selected since Phase 004 and
  already enforces awareness repository-wide, which is why this phase did not
  need to add it. It is also why an additional check was necessary:
  `datetime.now(UTC)` inside the domain layer satisfies every DTZ rule and
  violates invariant 25. `tests/architecture/test_clock_discipline.py` enforces
  location, which is the half no lint rule covers.

---

## The venue's millisecond convention

### S-10 — Binance Spot API: timestamps are milliseconds by default

- **Canonical location:** https://developers.binance.com/docs/binance-spot-api-docs/rest-api/general-api-information
- **Accessed:** 2026-08-14
- **Authority:** Primary — the venue publishing its own interface.
- **Supports:** "All time and timestamp related fields in the JSON responses are
  in **milliseconds by default**." Microsecond precision is available only by
  sending an `X-MBX-TIME-UNIT` header. Timestamp parameters such as `startTime`,
  `endTime` and `timestamp` may be passed in either unit. `recvWindow`
  "specifies for how long the request stays valid and may only be specified in
  milliseconds"; it defaults to 5000 ms and may not exceed 60000 ms.
- **Implication for GLOBIN:** the sole reason a millisecond convention exists at
  all, and the reason it is a *projection* rather than the representation — the
  unit is a property of the wire, not of GLOBIN. `recvWindow` is also the
  concrete case behind the flooring decision in
  [ADR-0035](../adr/0035-milliseconds-are-a-floored-projection.md): the venue
  validates a request against a window around its own clock, so a timestamp that
  has drifted *forward* is the one at risk of rejection, and truncation towards
  the past is the safe direction. **Nothing in Phase 009 calls this API.** The
  entry justifies a convention; the integration is Phases 033-048, and
  reconciling the two clocks is **Phase 040**.

---

## Facts this phase could not establish

### S-11 — The behaviour of a coarse system clock, not reproduced

- **Canonical location:** https://docs.python.org/3/library/time.html
- **Accessed:** 2026-08-14
- **Authority:** Primary for the interface; **not established** for the
  behaviour claimed below.
- **Supports:** `time.get_clock_info` reports an implementation and a resolution
  per clock, and those differ by platform and by CPython build. On this machine
  both clocks report `1e-07`. It is understood that a Windows host whose wall
  clock falls back to `GetSystemTimeAsFileTime()` has a granularity closer to
  15.6 ms, which would make two consecutive readings identical.
- **Implication for GLOBIN:** **not reproduced.** No machine exhibiting the
  coarse behaviour was available in this phase, so the claim is treated as
  plausible rather than verified. The response is defensive regardless and costs
  nothing: no test in this repository asserts that two real clock readings
  differ, only that the later is not smaller. If the coarse case never
  materialises the tests are still correct; if it does, they do not flake. The
  phase that pins interpreter and platform behaviour is **018**.
